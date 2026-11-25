#!/bin/sh
# Package manager hooks run as root so they can see every user's processes.
for executable in /proc/[0-9]*/exe; do
    path=$(readlink "$executable" 2>/dev/null) || continue
    case "$path" in
        /opt/loushang/*)
            echo 'Close Loushang GUI and TUI, then stop Loushang Web and AppHost before installing or removing this package.' >&2
            exit 1
            ;;
    esac
done
exit 0
