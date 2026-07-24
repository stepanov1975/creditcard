from __future__ import annotations

import ctypes
import os
from dataclasses import replace
from pathlib import Path

import pytest

import ccparser._traced_subprocess as traced_module


def _mapping_request(
    file_descriptor: int,
    protections: int,
    *,
    flags: int = 0,
) -> traced_module._SyscallInfo:
    info = traced_module._SyscallInfo()
    info.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    info.architecture = 0xC000003E
    info.data.entry.number = 9
    info.data.entry.arguments[2] = protections
    info.data.entry.arguments[3] = flags
    info.data.entry.arguments[4] = file_descriptor
    return info


def _worker_request(file_descriptor: int) -> traced_module._WorkerRequest:
    file_stat = os.fstat(file_descriptor)
    return traced_module._WorkerRequest(
        command=("synthetic",),
        cwd="/",
        environment=(),
        inherited_file_descriptors=(file_descriptor,),
        allowed_identities=frozenset(((file_stat.st_dev, file_stat.st_ino),)),
        input_file_descriptor=0,
        output_file_descriptor=1,
        error_file_descriptor=2,
        status_file_descriptor=2,
        stderr_to_stdout=False,
    )


def _filter_result(
    instructions: tuple[traced_module._SocketFilter, ...],
    *,
    architecture: int,
    syscall_number: int,
) -> int:
    accumulator = 0
    position = 0
    while position < len(instructions):
        instruction = instructions[position]
        if instruction.code == traced_module._BPF_LOAD_SYSCALL_NUMBER:
            accumulator = (
                architecture
                if instruction.constant == traced_module._SECCOMP_DATA_ARCHITECTURE_OFFSET
                else syscall_number
            )
            position += 1
        elif instruction.code == traced_module._BPF_JUMP_EQUAL:
            position += 1 + (
                instruction.jump_true
                if accumulator == instruction.constant
                else instruction.jump_false
            )
        elif instruction.code == traced_module._BPF_JUMP_BITS_SET:
            position += 1 + (
                instruction.jump_true
                if accumulator & instruction.constant
                else instruction.jump_false
            )
        elif instruction.code == traced_module._BPF_RETURN:
            return int(instruction.constant)
        else:
            raise AssertionError(f"unsupported test BPF instruction: {instruction.code}")
    raise AssertionError("filter did not return")


def test_mapping_policy_allows_read_execute_only_for_an_approved_file(
    tmp_path: Path,
) -> None:
    library = tmp_path / "approved.so"
    library.write_bytes(b"approved")
    file_descriptor = os.open(library, os.O_RDONLY)
    try:
        request = _worker_request(file_descriptor)

        assert traced_module._approved_mapping_request(
            os.getpid(),
            _mapping_request(file_descriptor, traced_module._PROT_EXEC),
            request,
        )
        assert not traced_module._approved_mapping_request(
            os.getpid(),
            _mapping_request(
                file_descriptor,
                traced_module._PROT_EXEC | traced_module._PROT_WRITE,
            ),
            request,
        )
        assert not traced_module._approved_mapping_request(
            os.getpid(),
            _mapping_request(
                file_descriptor,
                traced_module._PROT_EXEC,
                flags=traced_module._MAP_ANONYMOUS,
            ),
            request,
        )
    finally:
        os.close(file_descriptor)


def test_mapping_policy_rejects_an_unapproved_file(tmp_path: Path) -> None:
    approved = tmp_path / "approved.so"
    approved.write_bytes(b"approved")
    substitute = tmp_path / "substitute.so"
    substitute.write_bytes(b"substitute")
    approved_fd = os.open(approved, os.O_RDONLY)
    substitute_fd = os.open(substitute, os.O_RDONLY)
    try:
        request = _worker_request(approved_fd)

        assert not traced_module._approved_mapping_request(
            os.getpid(),
            _mapping_request(substitute_fd, traced_module._PROT_EXEC),
            request,
        )
    finally:
        os.close(substitute_fd)
        os.close(approved_fd)


def test_mapping_policy_rejects_personality_changes() -> None:
    info = traced_module._SyscallInfo()
    info.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    info.architecture = 0xC000003E
    info.data.entry.number = 135

    assert not traced_module._approved_mapping_request(
        os.getpid(),
        info,
        traced_module._WorkerRequest(
            command=("synthetic",),
            cwd="/",
            environment=(),
            inherited_file_descriptors=(),
            allowed_identities=frozenset(),
            input_file_descriptor=0,
            output_file_descriptor=1,
            error_file_descriptor=2,
            status_file_descriptor=2,
            stderr_to_stdout=False,
        ),
    )


def test_mapping_policy_rejects_execute_permission_gains() -> None:
    request = traced_module._WorkerRequest(
        command=("synthetic",),
        cwd="/",
        environment=(),
        inherited_file_descriptors=(),
        allowed_identities=frozenset(),
        input_file_descriptor=0,
        output_file_descriptor=1,
        error_file_descriptor=2,
        status_file_descriptor=2,
        stderr_to_stdout=False,
    )
    mprotect = traced_module._SyscallInfo()
    mprotect.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    mprotect.architecture = 0xC000003E
    mprotect.data.entry.number = 10
    mprotect.data.entry.arguments[2] = traced_module._PROT_EXEC
    shared_memory = traced_module._SyscallInfo()
    shared_memory.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    shared_memory.architecture = 0xC000003E
    shared_memory.data.entry.number = 30
    shared_memory.data.entry.arguments[2] = traced_module._SHM_EXEC

    assert not traced_module._approved_mapping_request(os.getpid(), mprotect, request)
    assert not traced_module._approved_mapping_request(os.getpid(), shared_memory, request)


def test_seccomp_filter_kills_syscalls_from_an_unexpected_architecture() -> None:
    architecture = 0xC000003E
    policy = traced_module._ARCHITECTURE_POLICIES[architecture]

    instructions = traced_module._selective_trace_instructions(architecture, policy)

    assert instructions[0].constant == traced_module._SECCOMP_DATA_ARCHITECTURE_OFFSET
    assert instructions[1].constant == architecture
    assert instructions[1].jump_true == 1
    assert instructions[1].jump_false == 0
    assert instructions[2].constant == traced_module._SECCOMP_RET_KILL_PROCESS
    assert instructions[3].constant == 0
    assert instructions[4].constant == traced_module._X32_SYSCALL_BIT
    assert instructions[4].jump_true == 0
    assert instructions[4].jump_false == 1
    assert instructions[5].constant == traced_module._SECCOMP_RET_KILL_PROCESS
    assert (
        _filter_result(
            instructions,
            architecture=architecture,
            syscall_number=435,
        )
        == traced_module._SECCOMP_RET_ERRNO_ENOSYS
    )
    assert (
        _filter_result(
            instructions,
            architecture=architecture,
            syscall_number=9,
        )
        == traced_module._SECCOMP_RET_TRACE
    )
    assert (
        _filter_result(
            instructions,
            architecture=architecture,
            syscall_number=39,
        )
        == traced_module._SECCOMP_RET_ALLOW
    )
    assert (
        _filter_result(
            instructions,
            architecture=0x40000003,
            syscall_number=9,
        )
        == traced_module._SECCOMP_RET_KILL_PROCESS
    )
    assert (
        _filter_result(
            instructions,
            architecture=architecture,
            syscall_number=traced_module._X32_SYSCALL_BIT | 9,
        )
        == traced_module._SECCOMP_RET_KILL_PROCESS
    )


@pytest.mark.parametrize(
    ("machine", "architecture", "native_seccomp_syscall"),
    (("x86_64", 0xC000003E, 317), ("aarch64", 0xC00000B7, 277)),
)
def test_filter_installation_uses_selected_policy_seccomp_syscall(
    monkeypatch: pytest.MonkeyPatch,
    machine: str,
    architecture: int,
    native_seccomp_syscall: int,
) -> None:
    sentinel_seccomp_syscall = 123_456
    native_policy = traced_module._ARCHITECTURE_POLICIES[architecture]
    assert native_policy.seccomp_syscall == native_seccomp_syscall
    policy = replace(native_policy, seccomp_syscall=sentinel_seccomp_syscall)
    syscall_numbers: list[int] = []

    class FakeLibc:
        def prctl(self, *arguments: object) -> int:
            return 0

        def syscall(self, syscall_number: int, *arguments: object) -> int:
            syscall_numbers.append(syscall_number)
            return 0

    monkeypatch.setitem(traced_module._ARCHITECTURE_POLICIES, architecture, policy)
    monkeypatch.setattr(traced_module.platform, "machine", lambda: machine)
    monkeypatch.setattr(traced_module, "_LIBC", FakeLibc())

    traced_module._install_selective_trace_filter()

    assert syscall_numbers == [sentinel_seccomp_syscall]


def test_execute_request_detection_covers_every_traced_execution_path() -> None:
    executable_mapping = _mapping_request(3, traced_module._PROT_EXEC)
    non_executable_mapping = _mapping_request(3, 0)
    mprotect = traced_module._SyscallInfo()
    mprotect.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    mprotect.architecture = 0xC000003E
    mprotect.data.entry.number = 10
    mprotect.data.entry.arguments[2] = traced_module._PROT_EXEC
    shared_memory = traced_module._SyscallInfo()
    shared_memory.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    shared_memory.architecture = 0xC000003E
    shared_memory.data.entry.number = 30
    shared_memory.data.entry.arguments[2] = traced_module._SHM_EXEC
    forbidden = traced_module._SyscallInfo()
    forbidden.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    forbidden.architecture = 0xC000003E
    forbidden.data.entry.number = 135

    assert traced_module._request_adds_execute(executable_mapping)
    assert not traced_module._request_adds_execute(non_executable_mapping)
    assert traced_module._request_adds_execute(mprotect)
    assert traced_module._request_adds_execute(shared_memory)
    assert traced_module._request_adds_execute(forbidden)


def test_clone_attempt_is_observed_before_the_kernel_can_hide_its_child() -> None:
    clone = traced_module._SyscallInfo()
    clone.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    clone.architecture = 0xC000003E
    clone.data.entry.number = 56

    assert traced_module._request_starts_concurrency(clone)
    assert traced_module._approved_mapping_request(
        os.getpid(),
        clone,
        traced_module._WorkerRequest(
            command=("synthetic",),
            cwd="/",
            environment=(),
            inherited_file_descriptors=(),
            allowed_identities=frozenset(),
            input_file_descriptor=0,
            output_file_descriptor=1,
            error_file_descriptor=2,
            status_file_descriptor=2,
            stderr_to_stdout=False,
        ),
    )


def test_clone_untraced_is_rejected_for_legacy_and_clone3_interfaces() -> None:
    request = traced_module._WorkerRequest(
        command=("synthetic",),
        cwd="/",
        environment=(),
        inherited_file_descriptors=(),
        allowed_identities=frozenset(),
        input_file_descriptor=0,
        output_file_descriptor=1,
        error_file_descriptor=2,
        status_file_descriptor=2,
        stderr_to_stdout=False,
    )
    legacy = traced_module._SyscallInfo()
    legacy.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    legacy.architecture = 0xC000003E
    legacy.data.entry.number = 56
    legacy.data.entry.arguments[0] = traced_module._CLONE_UNTRACED
    clone_arguments = ctypes.c_uint64(traced_module._CLONE_UNTRACED)
    clone3 = traced_module._SyscallInfo()
    clone3.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    clone3.architecture = 0xC000003E
    clone3.data.entry.number = 435
    clone3.data.entry.arguments[0] = ctypes.addressof(clone_arguments)
    clone3.data.entry.arguments[1] = ctypes.sizeof(clone_arguments)

    assert not traced_module._approved_mapping_request(os.getpid(), legacy, request)
    assert not traced_module._approved_mapping_request(os.getpid(), clone3, request)


def test_tracee_cannot_replace_the_seccomp_mapping_policy() -> None:
    request = traced_module._WorkerRequest(
        command=("synthetic",),
        cwd="/",
        environment=(),
        inherited_file_descriptors=(),
        allowed_identities=frozenset(),
        input_file_descriptor=0,
        output_file_descriptor=1,
        error_file_descriptor=2,
        status_file_descriptor=2,
        stderr_to_stdout=False,
    )
    seccomp = traced_module._SyscallInfo()
    seccomp.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    seccomp.architecture = 0xC000003E
    seccomp.data.entry.number = 317
    prctl_seccomp = traced_module._SyscallInfo()
    prctl_seccomp.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    prctl_seccomp.architecture = 0xC000003E
    prctl_seccomp.data.entry.number = 157
    prctl_seccomp.data.entry.arguments[0] = traced_module._PR_SET_SECCOMP
    harmless_prctl = traced_module._SyscallInfo()
    harmless_prctl.operation = traced_module._PTRACE_SYSCALL_INFO_SECCOMP
    harmless_prctl.architecture = 0xC000003E
    harmless_prctl.data.entry.number = 157
    harmless_prctl.data.entry.arguments[0] = 15  # PR_SET_NAME

    assert not traced_module._approved_mapping_request(os.getpid(), seccomp, request)
    assert not traced_module._approved_mapping_request(os.getpid(), prctl_seccomp, request)
    assert traced_module._approved_mapping_request(os.getpid(), harmless_prctl, request)
