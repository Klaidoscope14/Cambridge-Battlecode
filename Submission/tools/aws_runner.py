#!/usr/bin/env python3
"""Run tools/sprt.py A/B tests on an AWS spot instance (192 vCPU: ~800 games in 45 s, bit-identical to the Mac).

usage (from Submission/, after `aws login`):
  python3 tools/aws_runner.py ab VARIANT BASE OPP[,OPP...] [sprt args]   # up + sync + build + sprt + pull + down
  python3 tools/aws_runner.py batch FILE [--keep]   # FILE: one "VARIANT BASE OPPS [sprt args]" per line (# comments)
  python3 tools/aws_runner.py up | sync | build BOT... | sprt ARGS... | pull [--replays] | ssh CMD | status | down

- Results land in the local sprt cache ($TMPDIR/kessoku_sprt, per bot source hash), so tools/sprt.py and the analysis
  scripts read them as if the games had run locally (re-running sprt.py locally then only prints the verdict).
- `ab` and `batch` terminate the instance at the end, also on errors or Ctrl-C; pass --keep to leave it up for more runs
  (then `down` when done). Every instance also powers itself off (= terminates) after MAX_MINUTES (default 120).
- The instance installs the same cambc version as this machine, so both play the same engine; without a Linux wheel
  for that version the runner stops before launching anything.
- Spot instance types are tried in order until one launches (capacity varies by zone). Region: `aws configure get region`.
- Uses key pair `kessoku-runner` (~/.ssh/kessoku-runner.pem) and the SSH-only security group `kessoku-runner`; both are
  created on first use, and the group is opened to this machine's current public IP.
"""
import json, os, shlex, subprocess, sys, tempfile, time

P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Submission/
NAME = 'kessoku-runner'
KEY = os.path.expanduser(f'~/.ssh/{NAME}.pem')
STATE = os.path.expanduser('~/.cache/kessoku_aws.json')
TYPES = os.environ.get('AWS_TYPES', 'c7i.48xlarge,c6a.48xlarge,c7a.48xlarge,c6i.32xlarge').split(',')
MAX_MINUTES = int(os.environ.get('MAX_MINUTES', '120'))
# The runner must play the same engine as the Mac: install the local cambc version (override with CAMBC_VERSION).
CAMBC_VERSION = os.environ.get('CAMBC_VERSION') or subprocess.run(['cambc', '--version'], capture_output=True,
                                                                  text=True).stdout.split()[-1]
CACHE = os.path.join(tempfile.gettempdir(), 'kessoku_sprt')
SSH = ['ssh', '-i', KEY, '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=30']
REMOTE_ENV = 'export PATH=/home/ubuntu/venv/bin:$PATH; cd /home/ubuntu/Submission'
USER_DATA = f"""#!/bin/bash
shutdown -h +{MAX_MINUTES}
apt-get update -y && apt-get install -y python3-pip python3-venv rsync unzip
sudo -u ubuntu python3 -m venv /home/ubuntu/venv && sudo -u ubuntu /home/ubuntu/venv/bin/pip install cambc=={CAMBC_VERSION}
touch /home/ubuntu/READY
"""


def log(*a):
    print('[aws]', *a, file=sys.stderr, flush=True)


def aws(*args, check=True):
    r = subprocess.run(['aws', *args, '--region', region(), '--output', 'json'], capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f'aws {" ".join(args[:2])} failed: {r.stderr.strip()}')
    return json.loads(r.stdout) if r.stdout.strip() else {}


_region = None
def region():
    global _region
    if not _region:
        _region = subprocess.run(['aws', 'configure', 'get', 'region'], capture_output=True, text=True).stdout.strip() or 'ap-south-1'
    return _region


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, 'w'))


def running_instance():
    d = aws('ec2', 'describe-instances', '--filters', f'Name=tag:Name,Values={NAME}',
            'Name=instance-state-name,Values=pending,running')
    for r in d.get('Reservations', []):
        for i in r['Instances']:
            return i['InstanceId'], i.get('PublicIpAddress')
    return None, None


def ensure_key_and_group():
    if not os.path.exists(KEY):
        d = aws('ec2', 'create-key-pair', '--key-name', NAME)
        os.makedirs(os.path.dirname(KEY), exist_ok=True)
        with open(KEY, 'w') as f:
            f.write(d['KeyMaterial'])
        os.chmod(KEY, 0o400)
    g = aws('ec2', 'describe-security-groups', '--filters', f'Name=group-name,Values={NAME}')['SecurityGroups']
    if g:
        sg, cidrs = g[0]['GroupId'], {r['CidrIp'] for p in g[0]['IpPermissions'] for r in p.get('IpRanges', [])}
    else:
        vpc = aws('ec2', 'describe-vpcs', '--filters', 'Name=isDefault,Values=true')['Vpcs'][0]['VpcId']
        sg = aws('ec2', 'create-security-group', '--group-name', NAME, '--description', 'kessoku A/B runner, SSH only',
                 '--vpc-id', vpc)['GroupId']
        cidrs = set()
    ip = subprocess.run(['curl', '-s', 'https://checkip.amazonaws.com'], capture_output=True, text=True).stdout.strip()
    if f'{ip}/32' not in cidrs:
        aws('ec2', 'authorize-security-group-ingress', '--group-id', sg, '--protocol', 'tcp', '--port', '22',
            '--cidr', f'{ip}/32', check=False)
    return sg


def ssh(cmd, capture=False):
    ip = load_state()['ip']
    for k in range(4):  # 255 = ssh could not connect (network blip): retry; anything else is the command's own failure
        r = subprocess.run([*SSH, f'ubuntu@{ip}', cmd], capture_output=capture, text=True)
        if r.returncode != 255:
            break
        log(f'ssh connection failed, retry {k + 1}')
        time.sleep(10 * (k + 1))
    if r.returncode:
        raise SystemExit(f'remote command failed ({r.returncode}): {cmd[:120]}\n{(r.stderr or "")[-2000:]}')
    return r.stdout if capture else None


def linux_wheel_exists():
    r = subprocess.run(['curl', '-s', f'https://pypi.org/pypi/cambc/{CAMBC_VERSION}/json'], capture_output=True, text=True)
    try:
        return any('manylinux' in u['filename'] and 'x86_64' in u['filename'] for u in json.loads(r.stdout)['urls'])
    except Exception:
        return True  # PyPI unreachable: let the install on the instance decide


def up():
    if not linux_wheel_exists():
        raise SystemExit(f'cambc {CAMBC_VERSION} has no Linux x86_64 wheel on PyPI yet: AWS cannot run this engine; test locally')
    iid, ip = running_instance()
    if not iid:
        sg = ensure_key_and_group()
        ami = aws('ssm', 'get-parameter', '--name',
                  '/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id')['Parameter']['Value']
        ud = os.path.join(tempfile.gettempdir(), 'kessoku_userdata.sh')
        open(ud, 'w').write(USER_DATA)
        launched = False
        for attempt in range(6):  # a just-terminated spot request still counts against the limit for a minute or two
          for t in TYPES:
            r = subprocess.run(['aws', 'ec2', 'run-instances', '--region', region(), '--output', 'json', '--image-id', ami,
                                '--instance-type', t, '--key-name', NAME, '--security-group-ids', sg,
                                '--instance-market-options',
                                'MarketType=spot,SpotOptions={SpotInstanceType=one-time,InstanceInterruptionBehavior=terminate}',
                                '--instance-initiated-shutdown-behavior', 'terminate',
                                '--block-device-mappings',
                                'DeviceName=/dev/sda1,Ebs={VolumeSize=40,VolumeType=gp3,DeleteOnTermination=true}',
                                '--user-data', f'file://{ud}',
                                '--tag-specifications', f'ResourceType=instance,Tags=[{{Key=Name,Value={NAME}}}]'],
                               capture_output=True, text=True)
            if r.returncode == 0:
                iid = json.loads(r.stdout)['Instances'][0]['InstanceId']
                log(f'launched {t} spot {iid} (powers off after {MAX_MINUTES} min)')
                launched = True
                break
            log(f'{t}: {r.stderr.strip().splitlines()[-1][:160]}')
          if launched:
            break
          log('waiting 30 s before retrying the launch')
          time.sleep(30)
        if not launched:
            raise SystemExit('no instance type could be launched')
        subprocess.run(['aws', 'ec2', 'wait', 'instance-running', '--region', region(), '--instance-ids', iid], check=True)
        ip = aws('ec2', 'describe-instances', '--instance-ids', iid)['Reservations'][0]['Instances'][0]['PublicIpAddress']
    else:
        ensure_key_and_group()  # our IP may have changed since the instance started
    save_state({'id': iid, 'ip': ip})
    for k in range(60):
        r = subprocess.run([*SSH, f'ubuntu@{ip}', 'test -f READY && nproc'], capture_output=True, text=True)
        if r.returncode == 0:
            log(f'ready: {iid} {ip}, {r.stdout.strip()} vCPU')
            return
        time.sleep(10)
    raise SystemExit('instance did not become ready within 10 minutes')


def rsync(args):
    for k in range(4):
        if subprocess.run(['rsync', *args]).returncode == 0:
            return
        log(f'rsync failed, retry {k + 1}')
        time.sleep(10 * (k + 1))
    raise SystemExit('rsync failed')


def sync():
    ip = load_state()['ip']
    rsync(['-az', '--delete', '--exclude', '.cambc', '--exclude', 'replays', '--exclude', '__pycache__',
                    '--exclude', '*.repl26a', '-e', ' '.join(SSH), f'{P}/', f'ubuntu@{ip}:/home/ubuntu/Submission/'])
    log('synced Submission/')


def build(bots):
    bots = sorted(set(bots))
    # Different bots build in parallel; the same bot never twice at once (concurrent builds of one bot break games).
    ssh(f'{REMOTE_ENV}; printf "%s\\n" {" ".join(map(shlex.quote, bots))} | '
        f'xargs -P 8 -I@ sh -c "cambc build @ --release >/tmp/build-@.log 2>&1 || (echo BUILD FAILED @; tail -5 /tmp/build-@.log)"')
    log(f'built {len(bots)} bots')


def sprt(args):
    n = int(ssh('nproc', capture=True).strip())
    if '--jobs' not in args:
        args = [*args, '--jobs', str(max(1, n - 2))]
    if '--batch' not in args:
        args = [*args, '--batch', str(max(64, n * 2))]
    out = ssh(f'{REMOTE_ENV}; python3 tools/sprt.py {" ".join(map(shlex.quote, args))}', capture=True)
    print(out.strip().splitlines()[-1] if out.strip() else '(no output)', flush=True)


def pull(replays=False):
    ip = load_state()['ip']
    os.makedirs(CACHE, exist_ok=True)
    flt = [] if replays else ['--include', '*/', '--include', '*.json', '--exclude', '*']
    rsync(['-az', *flt, '-e', ' '.join(SSH), f'ubuntu@{ip}:/tmp/kessoku_sprt/', f'{CACHE}/'])
    log(f'results pulled into {CACHE}')


def down():
    iid, _ = running_instance()
    if iid:
        aws('ec2', 'terminate-instances', '--instance-ids', iid)
        log(f'terminated {iid}')
    else:
        log('no runner instance is running')
    save_state({})


def status():
    iid, ip = running_instance()
    if not iid:
        print('no runner instance running')
        return
    i = aws('ec2', 'describe-instances', '--instance-ids', iid)['Reservations'][0]['Instances'][0]
    print(f"{iid} {i['InstanceType']} {i['State']['Name']} {ip} since {i['LaunchTime']}")


def bots_of(line_args):
    v, b, opps = line_args[0], line_args[1], line_args[2]
    return [v, b, *opps.split(',')]


def run_lines(lines, keep):
    try:
        up()
        sync()
        build([x for la in lines for x in bots_of(la)])
        for la in lines:
            sprt(la)
        pull()
    finally:
        if not keep:
            down()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, rest = sys.argv[1], sys.argv[2:]
    keep = '--keep' in rest
    rest = [x for x in rest if x != '--keep']
    if cmd == 'ab':
        if len(rest) < 3:
            sys.exit(__doc__)
        run_lines([rest], keep)
    elif cmd == 'batch':
        lines = [shlex.split(l) for l in open(rest[0]) if l.strip() and not l.lstrip().startswith('#')]
        run_lines(lines, keep)
    elif cmd == 'up': up()
    elif cmd == 'sync': sync()
    elif cmd == 'build': build(rest)
    elif cmd == 'sprt': sprt(rest)
    elif cmd == 'pull': pull('--replays' in rest)
    elif cmd == 'ssh': ssh(f'{REMOTE_ENV}; {" ".join(rest)}')
    elif cmd == 'status': status()
    elif cmd == 'down': down()
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
