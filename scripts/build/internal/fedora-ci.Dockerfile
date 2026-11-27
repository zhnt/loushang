FROM registry.fedoraproject.org/fedora:43 AS acceptance
RUN dnf -y --setopt=install_weak_deps=False install \
    bash ca-certificates dbus-daemon file procps-ng shadow-utils sudo \
    xdotool xorg-x11-server-Xvfb && dnf clean all
ARG HOST_UID
ARG HOST_GID
RUN groupadd -o -g "$HOST_GID" builder && useradd -m -u "$HOST_UID" -g builder builder \
    && echo 'builder ALL=(root) NOPASSWD: ALL' > /etc/sudoers.d/loushang-ci

FROM acceptance AS build
RUN dnf -y --setopt=install_weak_deps=False install \
    desktop-file-utils findutils gcc gcc-c++ git glibc-devel gtk3-devel \
    libayatana-appindicator-gtk3-devel librsvg2-devel libxdo-devel make openssl-devel \
    pkgconf-pkg-config rpm-build webkit2gtk4.1-devel xdg-utils && dnf clean all
