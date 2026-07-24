"""Linux subprocess execution with a closed executable-mapping policy."""

from __future__ import annotations

import ctypes
import fcntl
import json
import os
import platform
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_PTRACE_TRACEME: Final = 0
_PTRACE_CONT: Final = 7
_PTRACE_SYSCALL: Final = 24
_PTRACE_SETOPTIONS: Final = 0x4200
_PTRACE_GETEVENTMSG: Final = 0x4201
_PTRACE_GET_SYSCALL_INFO: Final = 0x420E
_PTRACE_O_TRACESYSGOOD: Final = 0x00000001
_PTRACE_O_TRACEFORK: Final = 0x00000002
_PTRACE_O_TRACEVFORK: Final = 0x00000004
_PTRACE_O_TRACECLONE: Final = 0x00000008
_PTRACE_O_TRACEEXEC: Final = 0x00000010
_PTRACE_O_TRACEEXIT: Final = 0x00000040
_PTRACE_O_TRACESECCOMP: Final = 0x00000080
_PTRACE_O_EXITKILL: Final = 0x00100000
_PTRACE_EVENT_FORK: Final = 1
_PTRACE_EVENT_VFORK: Final = 2
_PTRACE_EVENT_CLONE: Final = 3
_PTRACE_EVENT_EXEC: Final = 4
_PTRACE_EVENT_EXIT: Final = 6
_PTRACE_EVENT_SECCOMP: Final = 7
_PTRACE_SYSCALL_INFO_ENTRY: Final = 1
_PTRACE_SYSCALL_INFO_EXIT: Final = 2
_PTRACE_SYSCALL_INFO_SECCOMP: Final = 3
_WAIT_ALL: Final = 0x40000000
_TRACE_OPTIONS: Final = (
    _PTRACE_O_TRACESYSGOOD
    | _PTRACE_O_TRACEFORK
    | _PTRACE_O_TRACEVFORK
    | _PTRACE_O_TRACECLONE
    | _PTRACE_O_TRACEEXEC
    | _PTRACE_O_TRACEEXIT
    | _PTRACE_O_TRACESECCOMP
    | _PTRACE_O_EXITKILL
)
_ALLOWED_SPECIAL_EXECUTABLE_MAPPINGS: Final = frozenset({"[vdso]", "[vsyscall]"})
_BROKER_FAILURE_STATUS: Final = b"broker-failure\n"
_RUNTIME_VIOLATION_STATUS: Final = b"runtime-violation\n"
_BROKER_SOURCE_BYTES: Final = Path(__file__).read_bytes()


class _SyscallEntry(ctypes.Structure):
    _fields_ = (("number", ctypes.c_uint64), ("arguments", ctypes.c_uint64 * 6))


class _SyscallExit(ctypes.Structure):
    _fields_ = (("return_value", ctypes.c_int64), ("is_error", ctypes.c_uint8))


class _SyscallData(ctypes.Union):
    _fields_ = (("entry", _SyscallEntry), ("exit", _SyscallExit))


class _SyscallInfo(ctypes.Structure):
    _fields_ = (
        ("operation", ctypes.c_uint8),
        ("architecture", ctypes.c_uint32),
        ("instruction_pointer", ctypes.c_uint64),
        ("stack_pointer", ctypes.c_uint64),
        ("data", _SyscallData),
    )


@dataclass(frozen=True, slots=True)
class _ArchitecturePolicy:
    mmap_syscall: int
    mprotect_syscalls: frozenset[int]
    shared_memory_syscall: int
    clone_syscalls: frozenset[int]
    clone3_syscall: int
    prctl_syscall: int
    seccomp_syscall: int
    concurrency_syscalls: frozenset[int]
    forbidden_syscalls: frozenset[int]

    @property
    def traced_syscalls(self) -> frozenset[int]:
        return frozenset(
            (
                self.mmap_syscall,
                self.shared_memory_syscall,
                self.clone3_syscall,
                self.prctl_syscall,
                self.seccomp_syscall,
                *self.mprotect_syscalls,
                *self.concurrency_syscalls,
                *self.forbidden_syscalls,
            )
        )


_ARCHITECTURE_POLICIES: Final = {
    # AUDIT_ARCH_X86_64
    0xC000003E: _ArchitecturePolicy(
        mmap_syscall=9,
        mprotect_syscalls=frozenset({10, 329}),
        shared_memory_syscall=30,
        clone_syscalls=frozenset({56}),
        clone3_syscall=435,
        prctl_syscall=157,
        seccomp_syscall=317,
        concurrency_syscalls=frozenset({56, 57, 58}),
        forbidden_syscalls=frozenset(
            {
                101,  # ptrace
                134,  # uselib
                135,  # personality
                311,  # process_vm_writev
                323,  # userfaultfd
                425,  # io_uring_setup
                438,  # pidfd_getfd
            }
        ),
    ),
    # AUDIT_ARCH_AARCH64
    0xC00000B7: _ArchitecturePolicy(
        mmap_syscall=222,
        mprotect_syscalls=frozenset({226, 288}),
        shared_memory_syscall=196,
        clone_syscalls=frozenset({220}),
        clone3_syscall=435,
        prctl_syscall=167,
        seccomp_syscall=277,
        concurrency_syscalls=frozenset({220}),
        forbidden_syscalls=frozenset(
            {
                92,  # personality
                117,  # ptrace
                271,  # process_vm_writev
                282,  # userfaultfd
                425,  # io_uring_setup
                438,  # pidfd_getfd
            }
        ),
    ),
}
_MACHINE_AUDIT_ARCHITECTURES: Final = {
    "aarch64": 0xC00000B7,
    "x86_64": 0xC000003E,
}
_PROT_EXEC: Final = 0x4
_PROT_WRITE: Final = 0x2
_MAP_ANONYMOUS: Final = 0x20
_SHM_EXEC: Final = 0x8000
_PR_SET_NO_NEW_PRIVS: Final = 38
_PR_SET_SECCOMP: Final = 22
_SECCOMP_SET_MODE_FILTER: Final = 1
_BPF_LOAD_SYSCALL_NUMBER: Final = 0x20
_BPF_JUMP_EQUAL: Final = 0x15
_BPF_JUMP_BITS_SET: Final = 0x45
_BPF_RETURN: Final = 0x06
_SECCOMP_RET_TRACE: Final = 0x7FF00000
_SECCOMP_RET_ALLOW: Final = 0x7FFF0000
_SECCOMP_RET_KILL_PROCESS: Final = 0x80000000
_SECCOMP_RET_ERRNO_ENOSYS: Final = 0x00050026
_SECCOMP_DATA_ARCHITECTURE_OFFSET: Final = 4
_X32_SYSCALL_BIT: Final = 0x40000000
_AUDIT_ARCH_X86_64: Final = 0xC000003E
_CLONE_UNTRACED: Final = 0x00800000


@dataclass(frozen=True, slots=True)
class _WorkerRequest:
    command: tuple[str, ...]
    cwd: str
    environment: tuple[tuple[str, str], ...]
    inherited_file_descriptors: tuple[int, ...]
    allowed_identities: frozenset[tuple[int, int]]
    input_file_descriptor: int
    output_file_descriptor: int
    error_file_descriptor: int
    status_file_descriptor: int
    stderr_to_stdout: bool

    @classmethod
    def from_json(cls, serialized: str) -> _WorkerRequest:
        raw = json.loads(serialized)
        if not isinstance(raw, dict):
            raise ValueError
        required = {
            "allowed_identities",
            "command",
            "cwd",
            "environment",
            "error_file_descriptor",
            "inherited_file_descriptors",
            "input_file_descriptor",
            "output_file_descriptor",
            "status_file_descriptor",
            "stderr_to_stdout",
        }
        if set(raw) != required:
            raise ValueError
        command = _string_tuple(raw["command"])
        environment_items = raw["environment"]
        if not isinstance(environment_items, list):
            raise ValueError
        environment: list[tuple[str, str]] = []
        for item in environment_items:
            pair = _string_tuple(item)
            if len(pair) != 2:
                raise ValueError
            environment.append((pair[0], pair[1]))
        identities = raw["allowed_identities"]
        if not isinstance(identities, list):
            raise ValueError
        allowed: set[tuple[int, int]] = set()
        for item in identities:
            if (
                not isinstance(item, list)
                or len(item) != 2
                or not all(isinstance(value, int) and value >= 0 for value in item)
            ):
                raise ValueError
            allowed.add((item[0], item[1]))
        cwd = raw["cwd"]
        stderr_to_stdout = raw["stderr_to_stdout"]
        integer_fields = tuple(
            raw[name]
            for name in (
                "input_file_descriptor",
                "output_file_descriptor",
                "error_file_descriptor",
                "status_file_descriptor",
            )
        )
        inherited = raw["inherited_file_descriptors"]
        if (
            not command
            or not isinstance(cwd, str)
            or not isinstance(stderr_to_stdout, bool)
            or not all(isinstance(value, int) and value >= 0 for value in integer_fields)
            or not isinstance(inherited, list)
            or not all(isinstance(value, int) and value >= 0 for value in inherited)
        ):
            raise ValueError
        return cls(
            command=command,
            cwd=cwd,
            environment=tuple(environment),
            inherited_file_descriptors=tuple(inherited),
            allowed_identities=frozenset(allowed),
            input_file_descriptor=integer_fields[0],
            output_file_descriptor=integer_fields[1],
            error_file_descriptor=integer_fields[2],
            status_file_descriptor=integer_fields[3],
            stderr_to_stdout=stderr_to_stdout,
        )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError
    return tuple(value)


_LIBC = ctypes.CDLL(None, use_errno=True)
_LIBC.ptrace.argtypes = (
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_void_p,
    ctypes.c_void_p,
)
_LIBC.ptrace.restype = ctypes.c_long
_LIBC.prctl.argtypes = (
    ctypes.c_int,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
)
_LIBC.prctl.restype = ctypes.c_int
_LIBC.syscall.restype = ctypes.c_long


class _SocketFilter(ctypes.Structure):
    _fields_ = (
        ("code", ctypes.c_ushort),
        ("jump_true", ctypes.c_ubyte),
        ("jump_false", ctypes.c_ubyte),
        ("constant", ctypes.c_uint32),
    )


class _SocketFilterProgram(ctypes.Structure):
    _fields_ = (("length", ctypes.c_ushort), ("filters", ctypes.POINTER(_SocketFilter)))


def _install_selective_trace_filter() -> None:
    architecture = _MACHINE_AUDIT_ARCHITECTURES.get(platform.machine().lower())
    if architecture is None:
        raise RuntimeError
    policy = _ARCHITECTURE_POLICIES.get(architecture)
    if policy is None:
        raise RuntimeError
    instructions = list(_selective_trace_instructions(architecture, policy))
    filter_array = (_SocketFilter * len(instructions))(*instructions)
    program = _SocketFilterProgram(len(instructions), filter_array)
    if _LIBC.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "no_new_privs unavailable")
    result = int(
        _LIBC.syscall(
            policy.seccomp_syscall,
            _SECCOMP_SET_MODE_FILTER,
            0,
            ctypes.byref(program),
        )
    )
    if result != 0:
        raise OSError(ctypes.get_errno(), "seccomp unavailable")


def _selective_trace_instructions(
    architecture: int,
    policy: _ArchitecturePolicy,
) -> tuple[_SocketFilter, ...]:
    instructions: list[_SocketFilter] = [
        _SocketFilter(
            _BPF_LOAD_SYSCALL_NUMBER,
            0,
            0,
            _SECCOMP_DATA_ARCHITECTURE_OFFSET,
        ),
        _SocketFilter(_BPF_JUMP_EQUAL, 1, 0, architecture),
        _SocketFilter(_BPF_RETURN, 0, 0, _SECCOMP_RET_KILL_PROCESS),
        _SocketFilter(_BPF_LOAD_SYSCALL_NUMBER, 0, 0, 0),
    ]
    if architecture == _AUDIT_ARCH_X86_64:
        instructions.extend(
            (
                _SocketFilter(_BPF_JUMP_BITS_SET, 0, 1, _X32_SYSCALL_BIT),
                _SocketFilter(_BPF_RETURN, 0, 0, _SECCOMP_RET_KILL_PROCESS),
            )
        )
    for syscall_number in sorted(policy.traced_syscalls):
        action = (
            _SECCOMP_RET_ERRNO_ENOSYS
            if syscall_number == policy.clone3_syscall
            else _SECCOMP_RET_TRACE
        )
        instructions.extend(
            (
                _SocketFilter(_BPF_JUMP_EQUAL, 0, 1, syscall_number),
                _SocketFilter(_BPF_RETURN, 0, 0, action),
            )
        )
    instructions.append(_SocketFilter(_BPF_RETURN, 0, 0, _SECCOMP_RET_ALLOW))
    return tuple(instructions)


def _ptrace(
    request: int,
    process_id: int,
    address: int | ctypes.c_void_p | None = None,
    data: int | ctypes.c_void_p | ctypes.Array[ctypes.c_char] | None = None,
) -> int:
    address_pointer = (
        address if isinstance(address, ctypes.c_void_p) else ctypes.c_void_p(address or 0)
    )
    if isinstance(data, ctypes.Array):
        data_pointer = ctypes.cast(data, ctypes.c_void_p)
    else:
        data_pointer = data if isinstance(data, ctypes.c_void_p) else ctypes.c_void_p(data or 0)
    result = int(_LIBC.ptrace(request, process_id, address_pointer, data_pointer))
    if result == -1:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
    return result


def _trace_me() -> None:
    try:
        _ptrace(_PTRACE_TRACEME, 0)
        _install_selective_trace_filter()
    except (OSError, RuntimeError):
        os._exit(126)


def _mapped_executable_identities(process_id: int) -> frozenset[tuple[int, int] | str]:
    mappings: set[tuple[int, int] | str] = set()
    content = Path(f"/proc/{process_id}/maps").read_text(encoding="utf-8")
    for line in content.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) < 5 or "x" not in fields[1]:
            continue
        path = fields[5] if len(fields) == 6 else ""
        if path.startswith("["):
            mappings.add(path)
            continue
        major_text, separator, minor_text = fields[3].partition(":")
        if separator != ":":
            raise RuntimeError
        device = os.makedev(int(major_text, 16), int(minor_text, 16))
        mappings.add((device, int(fields[4])))
    return frozenset(mappings)


def _mappings_are_allowed(process_id: int, allowed: frozenset[tuple[int, int]]) -> bool:
    try:
        mappings = _mapped_executable_identities(process_id)
    except (OSError, RuntimeError, ValueError):
        return False
    return all(
        mapping in _ALLOWED_SPECIAL_EXECUTABLE_MAPPINGS
        if isinstance(mapping, str)
        else mapping in allowed
        for mapping in mappings
    )


def _syscall_info(process_id: int) -> _SyscallInfo:
    buffer = ctypes.create_string_buffer(ctypes.sizeof(_SyscallInfo))
    available = _ptrace(
        _PTRACE_GET_SYSCALL_INFO,
        process_id,
        ctypes.sizeof(buffer),
        buffer,
    )
    if available < 24:
        raise RuntimeError
    return _SyscallInfo.from_buffer_copy(buffer)


def _event_message(process_id: int) -> int:
    message = ctypes.c_ulong()
    _ptrace(
        _PTRACE_GETEVENTMSG,
        process_id,
        data=ctypes.cast(ctypes.pointer(message), ctypes.c_void_p),
    )
    return int(message.value)


def _kill_tracees(process_ids: set[int]) -> None:
    for process_id in process_ids:
        with suppress(ProcessLookupError):
            os.kill(process_id, signal.SIGKILL)
    while process_ids:
        try:
            process_id, _status = os.waitpid(-1, _WAIT_ALL)
        except ChildProcessError:
            break
        process_ids.discard(process_id)


def _approved_mapping_request(
    process_id: int,
    info: _SyscallInfo,
    request: _WorkerRequest,
) -> bool:
    policy = _ARCHITECTURE_POLICIES.get(int(info.architecture))
    if policy is None or info.operation != _PTRACE_SYSCALL_INFO_SECCOMP:
        return False
    number = int(info.data.entry.number)
    arguments = info.data.entry.arguments
    if number == policy.seccomp_syscall or number in policy.forbidden_syscalls:
        return False
    if number == policy.prctl_syscall:
        return int(arguments[0]) != _PR_SET_SECCOMP
    if number in policy.concurrency_syscalls:
        return _concurrency_request_allowed(process_id, info, policy)
    if number == policy.mmap_syscall:
        protections = int(arguments[2])
        if protections & _PROT_EXEC == 0:
            return True
        if protections & _PROT_WRITE or int(arguments[3]) & _MAP_ANONYMOUS:
            return False
        raw_fd = int(arguments[4])
        file_descriptor = ctypes.c_int64(raw_fd).value
        if file_descriptor < 0:
            return False
        try:
            mapped = os.stat(f"/proc/{process_id}/fd/{file_descriptor}")
        except OSError:
            return False
        return (mapped.st_dev, mapped.st_ino) in request.allowed_identities
    if number in policy.mprotect_syscalls:
        return int(arguments[2]) & _PROT_EXEC == 0
    if number == policy.shared_memory_syscall:
        return int(arguments[2]) & _SHM_EXEC == 0
    return False


def _concurrency_request_allowed(
    process_id: int,
    info: _SyscallInfo,
    policy: _ArchitecturePolicy,
) -> bool:
    del process_id
    number = int(info.data.entry.number)
    if number in policy.clone_syscalls:
        flags = int(info.data.entry.arguments[0])
    else:
        return True
    return flags & _CLONE_UNTRACED == 0


def _request_adds_execute(info: _SyscallInfo) -> bool:
    policy = _ARCHITECTURE_POLICIES.get(int(info.architecture))
    if policy is None or info.operation != _PTRACE_SYSCALL_INFO_SECCOMP:
        return True
    number = int(info.data.entry.number)
    arguments = info.data.entry.arguments
    if number == policy.mmap_syscall or number in policy.mprotect_syscalls:
        return bool(int(arguments[2]) & _PROT_EXEC)
    if number == policy.shared_memory_syscall:
        return bool(int(arguments[2]) & _SHM_EXEC)
    return number == policy.seccomp_syscall or number in policy.forbidden_syscalls


def _request_starts_concurrency(info: _SyscallInfo) -> bool:
    policy = _ARCHITECTURE_POLICIES.get(int(info.architecture))
    return bool(
        policy is not None
        and info.operation == _PTRACE_SYSCALL_INFO_SECCOMP
        and int(info.data.entry.number) in policy.concurrency_syscalls
    )


def _traced_request_allowed(
    process_id: int,
    info: _SyscallInfo,
    request: _WorkerRequest,
    *,
    concurrency_observed: bool,
) -> bool:
    if concurrency_observed and _request_adds_execute(info):
        return False
    return _approved_mapping_request(process_id, info, request)


def _trace_process(process: subprocess.Popen[bytes], request: _WorkerRequest) -> int | None:
    active = {process.pid}
    concurrent_execution_observed = False
    root_return_code: int | None = None
    try:
        initial_id, initial_status = os.waitpid(process.pid, _WAIT_ALL | os.WUNTRACED)
        if (
            initial_id != process.pid
            or not os.WIFSTOPPED(initial_status)
            or os.WSTOPSIG(initial_status) != signal.SIGTRAP
        ):
            return None
        _ptrace(_PTRACE_SETOPTIONS, process.pid, data=_TRACE_OPTIONS)
        if not _mappings_are_allowed(process.pid, request.allowed_identities):
            return None
        _ptrace(_PTRACE_CONT, process.pid)
        while active:
            process_id, status = os.waitpid(-1, _WAIT_ALL | os.WUNTRACED)
            if os.WIFEXITED(status):
                active.discard(process_id)
                if process_id == process.pid:
                    root_return_code = os.WEXITSTATUS(status)
                continue
            if os.WIFSIGNALED(status):
                active.discard(process_id)
                if process_id == process.pid:
                    root_return_code = -os.WTERMSIG(status)
                continue
            if not os.WIFSTOPPED(status):
                return None
            stop_signal = os.WSTOPSIG(status)
            event = status >> 16
            if event in {_PTRACE_EVENT_FORK, _PTRACE_EVENT_VFORK, _PTRACE_EVENT_CLONE}:
                active.add(_event_message(process_id))
                concurrent_execution_observed = True
            elif event == _PTRACE_EVENT_EXEC:
                return None
            elif event == _PTRACE_EVENT_SECCOMP:
                info = _syscall_info(process_id)
                if not _traced_request_allowed(
                    process_id,
                    info,
                    request,
                    concurrency_observed=concurrent_execution_observed,
                ):
                    return None
                if _request_starts_concurrency(info):
                    concurrent_execution_observed = True
            elif event == _PTRACE_EVENT_EXIT and not _mappings_are_allowed(
                process_id, request.allowed_identities
            ):
                return None
            delivered_signal = 0
            if stop_signal not in {signal.SIGSTOP, signal.SIGTRAP, signal.SIGTRAP | 0x80}:
                delivered_signal = stop_signal
            _ptrace(_PTRACE_CONT, process_id, data=delivered_signal)
        return root_return_code
    except (ChildProcessError, OSError, RuntimeError, ValueError):
        return None
    finally:
        if active:
            _kill_tracees(active)


def _write_all(file_descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        offset += os.write(file_descriptor, content[offset:])


def _worker_main(serialized_request: str) -> int:
    try:
        request = _WorkerRequest.from_json(serialized_request)
        if tuple(Path("/proc/self/task").iterdir()) != (Path(f"/proc/self/task/{os.getpid()}"),):
            raise RuntimeError
        process = subprocess.Popen(
            request.command,
            cwd=request.cwd,
            env=dict(request.environment),
            stdin=request.input_file_descriptor,
            stdout=request.output_file_descriptor,
            stderr=(
                request.output_file_descriptor
                if request.stderr_to_stdout
                else request.error_file_descriptor
            ),
            pass_fds=request.inherited_file_descriptors,
            preexec_fn=_trace_me,
        )
        return_code = _trace_process(process, request)
        status = (
            _RUNTIME_VIOLATION_STATUS
            if return_code is None
            else f"return-code:{return_code}\n".encode("ascii")
        )
    except Exception:
        status = _BROKER_FAILURE_STATUS
    try:
        _write_all(request.status_file_descriptor, status)
    except Exception:
        return 125
    return 0


def _memfd(name: str, content: bytes = b"", *, sealed: bool = False) -> int:
    flags = os.MFD_CLOEXEC | (os.MFD_ALLOW_SEALING if sealed else 0)
    file_descriptor = os.memfd_create(name, flags=flags)
    try:
        _write_all(file_descriptor, content)
        os.lseek(file_descriptor, 0, os.SEEK_SET)
        if sealed:
            fcntl.fcntl(
                file_descriptor,
                fcntl.F_ADD_SEALS,
                fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_WRITE | fcntl.F_SEAL_SEAL,
            )
        return file_descriptor
    except Exception:
        os.close(file_descriptor)
        raise


def _read_fd(file_descriptor: int) -> bytes:
    os.lseek(file_descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(file_descriptor, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def run_traced_subprocess(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    inherited_file_descriptors: Sequence[int],
    allowed_file_descriptors: Sequence[int],
    timeout: float,
    input_bytes: bytes | None = None,
    stderr_to_stdout: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    """Run a child whose executable mappings must come from the approved FDs."""

    if sys.platform != "linux" or not command or timeout <= 0:
        raise RuntimeError("external runtime unavailable")
    allowed_identities = tuple(
        sorted(
            (file_stat.st_dev, file_stat.st_ino)
            for file_stat in map(os.fstat, allowed_file_descriptors)
        )
    )
    if not allowed_identities or len(allowed_identities) != len(set(allowed_identities)):
        raise RuntimeError("external runtime unavailable")
    descriptors: list[int] = []
    try:
        input_fd = _memfd("ccparser-traced-input", input_bytes or b"", sealed=True)
        descriptors.append(input_fd)
        output_fd = _memfd("ccparser-traced-output")
        descriptors.append(output_fd)
        error_fd = _memfd("ccparser-traced-error")
        descriptors.append(error_fd)
        status_fd = _memfd("ccparser-traced-status")
        descriptors.append(status_fd)
        broker_source_fd = _memfd(
            "ccparser-traced-broker-source",
            _BROKER_SOURCE_BYTES,
            sealed=True,
        )
        descriptors.append(broker_source_fd)
        request = {
            "allowed_identities": allowed_identities,
            "command": tuple(command),
            "cwd": str(cwd),
            "environment": tuple(sorted(environment.items())),
            "error_file_descriptor": error_fd,
            "inherited_file_descriptors": tuple(inherited_file_descriptors),
            "input_file_descriptor": input_fd,
            "output_file_descriptor": output_fd,
            "status_file_descriptor": status_fd,
            "stderr_to_stdout": stderr_to_stdout,
        }
        broker_command = (
            sys.executable,
            "-I",
            "-S",
            f"/proc/self/fd/{broker_source_fd}",
            json.dumps(request, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        )
        try:
            broker = subprocess.run(
                broker_command,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=dict(environment),
                pass_fds=tuple((*inherited_file_descriptors, *descriptors)),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise subprocess.TimeoutExpired(tuple(command), timeout) from error
        status = _read_fd(status_fd)
        stdout = _read_fd(output_fd)
        stderr = b"" if stderr_to_stdout else _read_fd(error_fd)
        if broker.returncode != 0 or not status.startswith(b"return-code:"):
            raise RuntimeError("external runtime unavailable")
        try:
            return_code = int(status.removeprefix(b"return-code:").strip())
        except ValueError:
            raise RuntimeError("external runtime unavailable") from None
        return subprocess.CompletedProcess(tuple(command), return_code, stdout, stderr)
    finally:
        for file_descriptor in reversed(descriptors):
            with suppress(OSError):
                os.close(file_descriptor)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(125)
    raise SystemExit(_worker_main(sys.argv[1]))
