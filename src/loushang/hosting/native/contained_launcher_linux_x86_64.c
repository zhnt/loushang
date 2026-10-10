#define _GNU_SOURCE
/* Linux x86-64 H6 containment launcher source.
 *
 * The release builder embeds the SHA-256 of this exact source as the profile
 * revision. A Product catalog must separately pin the compiled ELF digest.
 * This executable has no standalone Plugin admission authority.
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/close_range.h>
#include <linux/filter.h>
#include <linux/landlock.h>
#include <linux/sched.h>
#include <linux/seccomp.h>
#include <asm/unistd.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef LOUSHANG_PROFILE_SHA256
#error "The release builder must embed the source profile digest"
#endif

#if !defined(__linux__) || !defined(__x86_64__)
#error "This launcher only supports Linux x86-64"
#endif

static int parse_fd(const char *text, int *result) {
    char *end = NULL;
    long value;
    if (text == NULL || *text == '\0') return -1;
    errno = 0;
    value = strtol(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' || value < 0 || value > 0x7fffffff)
        return -1;
    *result = (int)value;
    return 0;
}

static int parse_fds(const char *text, int *launcher, int *payload, int *cwd) {
    int consumed = 0;
    if (sscanf(text, "%d,%d,%d%n", launcher, payload, cwd, &consumed) != 3 ||
        consumed <= 0 || text[consumed] != '\0' ||
        *launcher < 0 || *payload < 0 || *cwd < 0) return -1;
    return 0;
}

static int close_on_exec(int fd) {
    int flags = fcntl(fd, F_GETFD);
    return flags < 0 ? -1 : fcntl(fd, F_SETFD, flags | FD_CLOEXEC);
}

static int await_start_gate(int fd) {
    struct stat observed;
    unsigned char token;
    ssize_t count;
    if (fd < 3 || fstat(fd, &observed) != 0 || !S_ISFIFO(observed.st_mode) ||
        close_on_exec(fd) != 0) return -1;
    do {
        count = read(fd, &token, 1);
    } while (count < 0 && errno == EINTR);
    if (count != 1 || token != 'S' || close(fd) != 0) return -1;
    return 0;
}

static int install_query_landlock(void) {
    struct landlock_ruleset_attr rules = {
        .handled_access_fs = LANDLOCK_ACCESS_FS_EXECUTE,
    };
    int rules_fd = (int)syscall(__NR_landlock_create_ruleset,
                                &rules, sizeof(rules), 0);
    if (rules_fd < 0) return -1;
    int result = (int)syscall(__NR_landlock_restrict_self, rules_fd, 0);
    int saved_errno = errno;
    if (close(rules_fd) != 0) return -1;
    errno = saved_errno;
    return result;
}

#define QUERY_ALLOW(number) \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (number), 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)

static int install_query_profile(int payload) {
    struct rlimit limit = {.rlim_cur = 0, .rlim_max = 0};
    struct rlimit memory = {
        .rlim_cur = 512ULL * 1024ULL * 1024ULL,
        .rlim_max = 512ULL * 1024ULL * 1024ULL,
    };
    struct rlimit cpu = {.rlim_cur = 30, .rlim_max = 30};
    if (setrlimit(RLIMIT_CORE, &limit) != 0 ||
        setrlimit(RLIMIT_FSIZE, &limit) != 0 ||
        setrlimit(RLIMIT_AS, &memory) != 0 ||
        setrlimit(RLIMIT_CPU, &cpu) != 0 ||
        prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0 ||
        prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0 ||
        install_query_landlock() != 0) return -1;

    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, __X32_SYSCALL_BIT, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        /* The only input authority is the framed Worker protocol on stdin. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_read, 0, 3),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, STDIN_FILENO, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, nr)),
        /* Output is limited to the two captured streams. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_write, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, STDOUT_FILENO, 2, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, STDERR_FILENO, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, nr)),
        /* One exact sealed memfd exec; Landlock blocks pathname substitution. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_execveat, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (unsigned int)payload, 0, 3),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, args[4])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AT_EMPTY_PATH, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, nr)),
        /* Static libc startup and bounded computation; no FS or process APIs. */
        QUERY_ALLOW(__NR_brk),
        QUERY_ALLOW(__NR_mmap),
        QUERY_ALLOW(__NR_munmap),
        QUERY_ALLOW(__NR_mprotect),
        QUERY_ALLOW(__NR_madvise),
        QUERY_ALLOW(__NR_arch_prctl),
        QUERY_ALLOW(__NR_set_tid_address),
        QUERY_ALLOW(__NR_set_robust_list),
        QUERY_ALLOW(__NR_rseq),
        QUERY_ALLOW(__NR_rt_sigaction),
        QUERY_ALLOW(__NR_rt_sigprocmask),
        QUERY_ALLOW(__NR_rt_sigreturn),
        QUERY_ALLOW(__NR_sigaltstack),
        QUERY_ALLOW(__NR_fstat),
        QUERY_ALLOW(__NR_lseek),
        QUERY_ALLOW(__NR_getrandom),
        QUERY_ALLOW(__NR_clock_gettime),
        QUERY_ALLOW(__NR_nanosleep),
        QUERY_ALLOW(__NR_futex),
        QUERY_ALLOW(__NR_getpid),
        QUERY_ALLOW(__NR_gettid),
        QUERY_ALLOW(__NR_exit),
        QUERY_ALLOW(__NR_exit_group),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
    };
    struct sock_fprog program = {
        .len = (unsigned short)(sizeof(filter) / sizeof(filter[0])),
        .filter = filter,
    };
    return prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program);
}

static int install_profile(void) {
    const unsigned int namespace_clone_flags =
        CLONE_NEWNS | CLONE_NEWCGROUP | CLONE_NEWUTS | CLONE_NEWIPC |
        CLONE_NEWUSER | CLONE_NEWPID | CLONE_NEWNET;
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, __X32_SYSCALL_BIT, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_socket, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_setsid, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_setpgid, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_unshare, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_setns, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_clone3, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | ENOSYS),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_clone, 0, 4),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, namespace_clone_flags, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, nr)),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {
        .len = (unsigned short)(sizeof(filter) / sizeof(filter[0])),
        .filter = filter,
    };
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) return -1;
    return prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program);
}

int main(int argc, char **argv) {
    int payload, launcher, listed_payload, cwd, gate = -1, payload_index = 10;
    int gated, query_profile;
    char executable[64];
    char *environment[] = {NULL};
    if (argc < 11) return 80;
    gated = strcmp(argv[2], "loushang-static-containment-launch/v2") == 0 ||
            strcmp(argv[2], "loushang-static-query-containment-launch/v2") == 0;
    query_profile = strcmp(argv[2], "loushang-static-query-containment-launch/v1") == 0 ||
                    strcmp(argv[2], "loushang-static-query-containment-launch/v2") == 0;
    if (strcmp(argv[1], "--loushang-protocol") != 0 ||
        (!gated && !query_profile &&
         strcmp(argv[2], "loushang-static-containment-launch/v1") != 0) ||
        strcmp(argv[3], "--loushang-profile-sha256") != 0 ||
        strcmp(argv[5], "--loushang-payload-fd") != 0 ||
        strcmp(argv[7], "--loushang-preparation-fds") != 0) return 81;
    if (gated) {
        if (argc < 13 || strcmp(argv[9], "--loushang-start-gate-fd") != 0 ||
            strcmp(argv[11], "--") != 0 || parse_fd(argv[10], &gate) != 0)
            return 81;
        payload_index = 12;
    } else if (strcmp(argv[9], "--") != 0) return 81;
    if (strcmp(argv[4], LOUSHANG_PROFILE_SHA256) != 0) return 87;
    if (parse_fd(argv[6], &payload) != 0 ||
        parse_fds(argv[8], &launcher, &listed_payload, &cwd) != 0 ||
        payload != listed_payload || launcher == payload ||
        launcher == cwd || payload == cwd ||
        (gated && (gate == launcher || gate == payload || gate == cwd))) return 82;
    if (close_on_exec(launcher) != 0 || close_on_exec(payload) != 0 ||
        close_on_exec(cwd) != 0) return 83;
    if (query_profile && gated && await_start_gate(gate) != 0) return 88;
    if (query_profile &&
        syscall(__NR_close_range, 3U, ~0U, CLOSE_RANGE_CLOEXEC) != 0)
        return 83;
    if ((query_profile ? install_query_profile(payload) : install_profile()) != 0)
        return 84;
    if (!query_profile && gated && await_start_gate(gate) != 0) return 88;
    if (query_profile) {
        syscall(__NR_execveat, payload, "", &argv[payload_index], environment,
                AT_EMPTY_PATH);
        return 86;
    }
    if (snprintf(executable, sizeof(executable), "/proc/self/fd/%d", payload) >=
        (int)sizeof(executable)) return 85;
    execve(executable, &argv[payload_index], environment);
    return 86;
}
