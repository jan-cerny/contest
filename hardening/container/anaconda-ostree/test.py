#!/usr/bin/python3

from lib import results, oscap, versions, virt, podman, util
from conf import remediation


virt.Host.setup()

_, variant, profile = util.get_test_name().rsplit('/', 2)

oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())

# note that the .wipe() is necessary here, as we are not calling any .install()
# function that would normally perform it
guest = virt.Guest()
guest.wipe()
guest.generate_ssh_keypair()

# select appropriate container image based on host OS
major = versions.rhel.major
minor = versions.rhel.minor
if versions.rhel.is_true_rhel():
    src_image = f'images.paas.redhat.com/testingfarm/rhel-bootc:{major}.{minor}'
else:
    src_image = f'quay.io/centos-bootc/centos-bootc:stream{major}'

# RHEL-9 and older use 'maint-1.3' openscap git repo branch, newer use 'main'
if versions.rhel <= 9:
    copr = 'packit/OpenSCAP-openscap-maint-1.3'
else:
    copr = 'packit/OpenSCAP-openscap-main'

# prepare a Container file for making a hardened image
cfile = podman.Containerfile()
cfile += util.dedent(fr'''
    FROM {src_image}
    RUN dnf -y install dnf-plugins-core
    RUN dnf -y copr enable {copr} centos-stream-{versions.rhel.major}-x86_64
    RUN dnf -y install openscap-utils
    COPY remediation-ds.xml /root/.
    RUN oscap-bootc --profile '{profile}' \
        --results-arf /root/remediation-arf.xml /root/remediation-ds.xml
    # hack sshd cmdline to allow root login
    RUN echo "OPTIONS=-oPermitRootLogin=yes" >> /etc/sysconfig/sshd
''')
cfile.add_ssh_pubkey(guest.ssh_pubkey)
cfile.write_to('Containerfile')

podman.podman('image', 'build', '--tag', 'contest-hardened', '.')

ks = virt.Kickstart()

# install the VM, using a locally-hosted podman registry serving
# the hardened image for Anaconda's ostreecontainer
with podman.Registry(host_addr=virt.NETWORK_HOST) as registry:
    image_url = registry.push('contest-hardened')
    ks.append(f'ostreecontainer --url {image_url}')
    # Anaconda doesn't expose ostree --insecure-skip-tls-verification,
    # work around it using registries.conf
    raddr, rport = registry.get_listen_addr()
    ks.add_pre(
        fr'''echo -e '[[registry]]\nlocation = "{raddr}:{rport}"\n'''
        r'''insecure = true\n' >> /etc/containers/registries.conf'''
    )
    guest.install_basic(kickstart=ks)

# boot up and scan the VM
with guest.booted():
    # copy the original DS to the guest
    guest.copy_to(util.get_datastream(), 'scan-ds.xml')
    # scan the remediated system
    proc, lines = guest.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' --results-arf scan-arf.xml scan-ds.xml'
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    guest.copy_from('report.html')
    guest.copy_from('remediation-arf.xml')
    guest.copy_from('scan-arf.xml')

tar = [
    'tar', '-cvJf', 'results-arf.tar.xz', 'remediation-arf.xml', 'scan-arf.xml',
]
util.subprocess_run(tar, check=True)

results.report_and_exit(logs=['report.html', 'results-arf.tar.xz'])
