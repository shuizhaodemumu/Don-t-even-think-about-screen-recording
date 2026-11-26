# Match Fedora's X.Org modular loader, whose drivers use late symbol binding.
%undefine _hardened_build
%undefine _strict_symbol_defs_build
%global debug_package %{nil}
%global use_source_date_epoch_as_buildtime 1
%global xserver_version 21.1.26
%global modules %{_libdir}/%{name}/modules
%global __provides_exclude_from ^%{modules}/.*$

Name:           x11-showcase
Version:        0.1.0
Release:        1%{?dist}
Summary:        Dedicated X11 exhibition server with black image readback
License:        Adobe-Display-PostScript AND BSD-3-Clause AND DEC-3-Clause AND HPND AND HPND-sell-MIT-disclaimer-xserver AND HPND-sell-variant AND ICU AND ISC AND MIT AND MIT-open-group AND NTP AND SGI-B-2.0 AND SMLNJ AND X11 AND X11-distribute-modifications-variant
URL:            https://www.x.org/
Source0:        https://www.x.org/releases/individual/xserver/xorg-server-%{xserver_version}.tar.xz
Source1:        x11-showcase
Source2:        demo.mp4
Source3:        LICENSE.showcase
Source4:        README.md
Patch0:         display-readback.patch

BuildRequires:  gcc gawk kernel-headers pkgconf-pkg-config meson ninja-build patch python3
BuildRequires:  bison flex
BuildRequires:  xorg-x11-proto-devel xorg-x11-xtrans-devel
BuildRequires:  libXfont2-devel libxkbfile-devel libXau-devel libxshmfence-devel pixman-devel
BuildRequires:  dbus-devel systemd-devel openssl-devel libdrm-devel libxcvt-devel libpciaccess-devel
BuildRequires:  libxcb-devel xcb-util-devel xcb-util-image-devel xcb-util-wm-devel xcb-util-keysyms-devel xcb-util-renderutil-devel
Requires:       python3 libX11%{?_isa} xkbcomp xkeyboard-config
Requires:       /usr/bin/ffmpeg /usr/bin/ffplay /usr/bin/dbus-run-session /usr/bin/loginctl
Suggests:       xorg-x11-drv-libinput%{?_isa}

%description
A dedicated Fedora X11 display for exhibitions. Attached X11 clients receive
black pixels through core and MIT-SHM image readback while the display shows
the content. Includes native Xorg, nested Xephyr, and a virtual Xvfb for tests.

%prep
echo "c8609f9cdafde14de7ec7cb406dac9507add1d536df8d3c3e3d3d9c1cd864066  %{SOURCE0}" | sha256sum -c -
%autosetup -p1 -n xorg-server-%{xserver_version}
install -pm 0644 %{SOURCE3} LICENSE.showcase
install -Dpm 0644 %{SOURCE4} showcase/README.md

%build
%set_build_flags
export CFLAGS="$CFLAGS -ffile-prefix-map=$PWD=/usr/src/debug/%{name}-%{version}"
%meson \
    -Dxorg=true -Dxephyr=true -Dxvfb=true -Dxnest=false \
    -Dglamor=false -Dglx=false -Ddri1=false -Ddri2=false -Ddri3=false -Dxinerama=false \
    -Ddrm=true -Dudev=true -Dudev_kms=true -Dsystemd_logind=true -Dlibunwind=false \
    -Dxselinux=false -Dsecure-rpc=false -Dint10=false -Dsuid_wrapper=false -Dxdmcp=false \
    -Dxdm-auth-1=false -Dxv=false -Dxvmc=false -Ddga=false -Dagp=false -Dxf86bigfont=false \
    -Dxf86-input-inputtest=false -Ddocs=false -Ddevel-docs=false -Ddocs-pdf=false \
    -Dxkb_dir=%{_datadir}/X11/xkb -Dxkb_bin_dir=%{_bindir} -Dxkb_output_dir=%{_localstatedir}/lib/xkb \
    -Ddefault_font_path=catalogue:/etc/X11/fontpath.d,built-ins -Dmodule_dir=%{modules} \
    -Dfallback_input_driver=libinput -Dlog_dir=%{_localstatedir}/log -Dsha1=libcrypto

ninja -C %{_vpath_builddir} %{?_smp_mflags} hw/xfree86/Xorg hw/kdrive/ephyr/Xephyr hw/vfb/Xvfb \
    hw/xfree86/drivers/modesetting/modesetting_drv.so hw/xfree86/dixmods/libshadow.so \
    hw/xfree86/loader/xorg_symbol_test hw/xfree86/libxorgserver.so

%install
install -d %{buildroot}%{_libexecdir}/%{name} %{buildroot}%{modules}/{drivers,input}
install -m 0755 %{_vpath_builddir}/hw/xfree86/Xorg %{_vpath_builddir}/hw/kdrive/ephyr/Xephyr \
    %{_vpath_builddir}/hw/vfb/Xvfb %{buildroot}%{_libexecdir}/%{name}/
install -m 0755 %{_vpath_builddir}/hw/xfree86/drivers/modesetting/modesetting_drv.so \
    %{buildroot}%{modules}/drivers/
install -m 0755 %{_vpath_builddir}/hw/xfree86/dixmods/libshadow.so %{buildroot}%{modules}/
ln -s ../../../xorg/modules/input/libinput_drv.so %{buildroot}%{modules}/input/libinput_drv.so
install -D -m 0755 %{SOURCE1} %{buildroot}%{_bindir}/%{name}
install -D -m 0644 %{SOURCE2} %{buildroot}%{_datadir}/%{name}/demo.mp4

%check
meson test -C %{_vpath_builddir} --no-rebuild --print-errorlogs 'modesetting symbol test'
%{__python3} %{buildroot}%{_bindir}/%{name} --help >/dev/null

%files
%license COPYING LICENSE.showcase
%doc showcase/README.md
%{_bindir}/%{name}
%{_libexecdir}/%{name}/
%{_libdir}/%{name}/
%{_datadir}/%{name}/

%changelog
* Thu Nov 26 2026 X11 Showcase contributors <x11-showcase@localhost> - 0.1.0-1
- Build dedicated X11 servers from X.Org 21.1.26 for Fedora exhibitions.
