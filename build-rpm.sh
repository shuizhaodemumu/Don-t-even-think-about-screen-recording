#!/usr/bin/env bash
# Build with Fedora's rpm-build and the BuildRequires declared in the spec.
set -euo pipefail
repo=$(cd "$(dirname "$0")" && pwd)
build_dir=$(mktemp -d)
mkdir -p "$build_dir"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
src="$build_dir/SOURCES"
upstream=xorg-server-21.1.26.tar.xz
curl --fail --location --retry 2 "https://www.x.org/releases/individual/xserver/$upstream" --output "$src/$upstream"
(cd "$src" && sha256sum -c - <<<"c8609f9cdafde14de7ec7cb406dac9507add1d536df8d3c3e3d3d9c1cd864066  $upstream")
install -m 0644 "$repo"/{display-readback.patch,demo.mp4,README.md,x11-showcase} "$src/"
install -m 0644 "$repo/LICENSE" "$src/LICENSE.showcase"
install -m 0644 "$repo/x11-showcase.spec" "$build_dir/SPECS/"
rpmbuild --define "_topdir $build_dir" -ba "$build_dir/SPECS/x11-showcase.spec"
printf 'RPMs are in %s/RPMS and %s/SRPMS\n' "$build_dir" "$build_dir"
