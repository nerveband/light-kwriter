APP = 'light-kwriter'
PORT = 8765
"""Local-only browser UI and USBNetwork helper. Python standard library only."""
import sys
import base64
import gzip
import io
import tarfile
import hashlib
import json
import os
import pty
import select
import shlex
import subprocess
import threading
import socket
import ipaddress
from concurrent.futures import ThreadPoolExecutor
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
default_data = Path.home()/"Library"/"Application Support" if sys.platform == "darwin" else Path(os.environ.get("XDG_DATA_HOME",str(Path.home()/".local"/"share")))
DATA = Path(os.environ.get("EINK_DATA_DIR", str(default_data / APP)))
DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
CONFIG = ROOT / "device.json"
config = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
if not config:
    usb_config = DATA / "usb-ssh.conf"
    known_hosts = DATA / "known_hosts"
    usb_config.write_text("Host kindle-usb\n HostName 192.168.15.244\n User root\n IdentityAgent none\n PubkeyAuthentication no\n PreferredAuthentications password\n StrictHostKeyChecking accept-new\n UserKnownHostsFile \"" + str(known_hosts) + "\"\n")
    config = {"ssh_config":str(usb_config),"hosts":{"usb":"kindle-usb","wifi":"kindle-wifi"}}
    CONFIG.write_text(json.dumps(config,indent=2))

class Kindle:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.fd = None
        self.connected = False
        self.enabled = False
        self.message = "Not connected"
        self.latency = None
        self.pending = None
        self.timer = None
        self.assets = None
        self.sequence = 0
        self.transport = "usb"
        self.auto_config = None
        self.wake = threading.Event()
        self.asset_digest = None
        self.last_image = None
        self.last_rotation = None
        threading.Thread(target=self.work, daemon=True).start()

    def read_until(self, marker, timeout=12):
        data = b""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if select.select([self.fd], [], [], min(0.3, max(0, end-time.monotonic())))[0]:
                chunk = os.read(self.fd, 65536)
                if not chunk:
                    break
                data += chunk
                if b"password:" in data.lower():
                    os.write(self.fd, b"\n")
                    data = data.replace(b"password:", b"")
                if marker in data:
                    return data.decode(errors="replace")
        raise ConnectionError("Kindle did not respond")

    def discover_wifi(self):
        alias = config.get("hosts", {}).get("wifi", "kindle-wifi")
        args = ["ssh", "-G"]
        if config.get("ssh_config"): args += ["-F", config["ssh_config"]]
        values = subprocess.check_output(args + [alias], stderr=subprocess.DEVNULL, text=True)
        resolved = dict(line.split(" ",1) for line in values.splitlines() if " " in line)
        host, port = resolved["hostname"], int(resolved.get("port",2222))
        try: ipaddress.ip_address(host)
        except ValueError: raise ConnectionError("Pair Wi-Fi over USB first")
        try:
            connection = socket.create_connection((host,port),.3)
            connection.close()
            return
        except OSError: pass
        self.message = "Finding your Kindle on Wi-Fi…"
        network = ipaddress.ip_network(host + "/24",strict=False)
        def probe(address):
            try:
                with socket.create_connection((str(address),port),.5) as connection:
                    connection.settimeout(1.2)
                    banner = connection.recv(100)
                    if b"SSH-" in banner and b"dropbear" in banner.lower(): return str(address)
            except OSError: pass
        with ThreadPoolExecutor(max_workers=24) as pool:
            found = next((address for address in pool.map(probe,network.hosts()) if address),None)
        if found:
            path = DATA / "discovered-ssh.conf"
            base = str(Path(config["ssh_config"]).expanduser()).replace('"','')
            path.write_text("Host " + alias + "\n HostName " + found + "\nInclude \"" + base + "\"\n")
            self.auto_config = str(path)

    def connect(self):
        master, slave = pty.openpty()
        args = ["ssh"]
        if self.transport == "wifi": self.discover_wifi()
        selected_config = self.auto_config or config.get("ssh_config")
        if selected_config:
            args += ["-F", str(Path(selected_config).expanduser())]
        args += ["-tt", "-o", "BatchMode=no", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=3", "-o", "ServerAliveInterval=2", "-o", "ServerAliveCountMax=2", config.get("hosts", {}).get(self.transport, config.get("host", "kindle-usb")), "stty -echo; printf 'EINK_READY\\n'; while IFS= read -r line; do eval \"$line\"; printf '\\nEINK_DONE\\n'; done"]
        self.process = subprocess.Popen(args, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        self.fd = master
        self.read_until(b"EINK_READY")
        state = self.command("/usr/bin/lipc-get-prop com.lab126.powerd status")
        self.command("/usr/bin/lipc-set-prop com.lab126.powerd preventScreenSaver 1")
        if "Screen Saver" in state:
            self.command("/usr/bin/lipc-set-prop com.lab126.powerd wakeUp 1")
        self.connected = True
        self.message = "Connected"

    def command(self, command):
        self.sequence += 1
        marker = ("EINK_RESULT_"+str(self.sequence)).encode()
        payload = (command + "\n printf '\\n" + marker.decode() + "\\n'\n").encode()
        remaining = memoryview(payload)
        while remaining:
            remaining = remaining[os.write(self.fd,remaining):]
        result = self.read_until(marker)
        if "EINK_FAILED" in result:
            raise RuntimeError("Device command failed")
        return result

    def upload(self, path, data):
        encoded = base64.b64encode(gzip.compress(data)).decode()
        target = shlex.quote(path)
        if len(encoded) < 2400:
            self.command("printf '%s' '"+encoded+"' | /mnt/us/usbnet/bin/openssl base64 -d -A | gzip -d > "+target+"; test -s "+target+" || echo EINK_FAILED")
            return
        staging = "/tmp/"+APP+"-upload.b64"
        commands = [": > "+staging]
        for start in range(0, len(encoded), 2800):
            commands.append("printf '%s' '" + encoded[start:start+2800] + "' >> "+staging)
        commands.append("/mnt/us/usbnet/bin/openssl base64 -d -A -in "+staging+" | gzip -d > " + target + "; test -s " + target + " || echo EINK_FAILED")
        self.command("\n".join(commands))

    def upload_bundle(self, directory, files):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer,mode="w",format=tarfile.USTAR_FORMAT) as archive:
            for name, content in files.items():
                item = tarfile.TarInfo(name)
                item.size = len(content)
                item.mode = 0o600
                archive.addfile(item,io.BytesIO(content))
        self.upload("/tmp/"+APP+"-bundle.tar",buffer.getvalue())
        self.command("/mnt/us/usbnet/bin/bsdtar -xf /tmp/"+APP+"-bundle.tar -C "+shlex.quote(directory)+" || echo EINK_FAILED")

    def pair_wifi(self):
        """Use the trusted USB connection to set up Wi-Fi without device typing."""
        import re
        pairing = DATA / "pairing"
        pairing.mkdir(mode=0o700, exist_ok=True)
        key = pairing / "device-key"
        if not key.exists():
            subprocess.run(["ssh-keygen","-q","-t","ed25519","-N","","-C","eink-local-app","-f",str(key)],check=True,stdout=subprocess.DEVNULL)
        base_config = config.get("ssh_config")
        original_config = config.get("usb_config", base_config or str(Path.home()/".ssh"/"config"))
        usb_alias = config.get("hosts",{}).get("usb","kindle-usb")
        args = ["ssh","-G"]
        if base_config: args += ["-F",base_config]
        resolved = dict(line.split(" ",1) for line in subprocess.check_output(args+[usb_alias],text=True,stderr=subprocess.DEVNULL).splitlines() if " " in line)
        self.close()
        self.transport = "usb"
        self.auto_config = None
        self.connect()
        reply = self.command("printf WIFI_ADDRESS=; ifconfig wlan0 | awk '/inet addr:/{split($2,a,\":\"); print a[2]}'")
        match = re.search(r"WIFI_ADDRESS=(\d+\.\d+\.\d+\.\d+)",reply)
        if not match: raise ValueError("Join Wi-Fi on your Kindle first, then pair again")
        address = str(ipaddress.ip_address(match.group(1)))
        self.command("mkdir -p /mnt/us/eink-wifi /mnt/us/extensions/eink-wifi")
        self.upload("/tmp/eink-app-key.pub",key.with_suffix(".pub").read_bytes())
        self.command("grep -q -F -f /tmp/eink-app-key.pub /mnt/us/usbnet/etc/authorized_keys 2>/dev/null || cat /tmp/eink-app-key.pub >> /mnt/us/usbnet/etc/authorized_keys; chmod 600 /mnt/us/usbnet/etc/authorized_keys; rm -f /tmp/eink-app-key.pub")
        script = b"""#!/bin/sh
if [ -f /mnt/us/eink-wifi/sshd.pid ] && kill -0 $(cat /mnt/us/eink-wifi/sshd.pid) 2>/dev/null; then exit 0; fi
address=$(ifconfig wlan0 | awk '/inet addr:/{split($2,a,":"); print a[2]}')
[ -n "$address" ] || exit 1
/mnt/us/usbnet/bin/dropbearmulti dropbear -s -j -k -p "$address:2222" -P /mnt/us/eink-wifi/sshd.pid
/usr/sbin/iptables -I INPUT 1 -i wlan0 -p tcp --dport 2222 -j ACCEPT
"""
        self.upload("/mnt/us/eink-wifi/start.sh",script)
        self.upload("/mnt/us/extensions/eink-wifi/menu.json",b'{"name":"E-reader Wi-Fi","items":[{"name":"Start secure Wi-Fi connection","action":"sh /mnt/us/eink-wifi/start.sh"}]}')
        self.command("sh /mnt/us/eink-wifi/start.sh; test -s /mnt/us/eink-wifi/sshd.pid || echo EINK_FAILED")
        ssh_config = pairing / "ssh.conf"
        lines = ["Host kindle-wifi", " HostName "+address, " Port 2222", " User root", " IdentityAgent none", " IdentitiesOnly yes", " IdentityFile \""+str(key)+"\"", " PasswordAuthentication no", " BatchMode yes", " StrictHostKeyChecking yes", " HostKeyAlias "+resolved.get("hostkeyalias",resolved["hostname"]), " UserKnownHostsFile "+resolved["userknownhostsfile"]]
        lines += ['Include "'+str(Path(original_config).expanduser())+'"']
        ssh_config.write_text("\n".join(lines)+"\n")
        config.update({"ssh_config":str(ssh_config),"usb_config":original_config,"hosts":{"usb":usb_alias,"wifi":"kindle-wifi"}})
        CONFIG.write_text(json.dumps(config,indent=2))
        self.close()
        self.transport = "wifi"
        self.enabled = True
        self.message = "Wi-Fi paired · connecting…"
        self.wake.set()

    def close(self):
        self.connected = False
        self.asset_digest = None
        self.last_image = None
        self.last_rotation = None
        if self.process:
            self.process.terminate()
            self.process = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def work(self):
        while True:
            frame = None
            if not self.enabled:
                time.sleep(0.1)
                continue
            try:
                with self.lock:
                    if not self.connected:
                        self.message = "Connecting…"
                        self.connect()
                    frame = self.pending
                    self.pending = None
                    if frame:
                        start = time.monotonic()
                        raw = base64.b64decode(frame["image"])
                        parts = raw.split(b"\n",3)
                        width, height = map(int,parts[1].split())
                        full = frame.get("full") or self.last_rotation != frame["rotation"] or self.last_image is None
                        if self.last_rotation != frame["rotation"]:
                            self.command("test ! -f /tmp/firepace.pid || kill $(cat /tmp/firepace.pid) 2>/dev/null; /usr/bin/lipc-set-prop com.lab126.powerd preventScreenSaver 1; /mnt/us/usbnet/bin/fbdepth -q -r " + str(frame["rotation"]))
                        self.upload("/tmp/kwriter.pgm", raw)
                        top, bottom = 0, height
                        if not full and self.last_image:
                            old = self.last_image.split(b"\n",3)[3]
                            new = parts[3]
                            changed = [row for row in range(height) if old[row*width:(row+1)*width] != new[row*width:(row+1)*width]]
                            if changed: top, bottom = changed[0], changed[-1]+1
                            else: bottom = 0
                        self.command("/mnt/us/usbnet/bin/fbink -q -b -g file=/tmp/kwriter.pgm || echo EINK_FAILED")
                        if bottom:
                            refresh = "-f -s" if full else f"-s top={top},left=0,width={width},height={bottom-top}"
                            self.command("/mnt/us/usbnet/bin/fbink -q " + refresh + " || echo EINK_FAILED")
                        self.last_image, self.last_rotation = raw, frame["rotation"]
                        self.latency = round((time.monotonic()-start)*1000)
                        self.message = "Synced"
                    elif APP == "firepace" and self.timer:
                        result = self.command("test ! -f /tmp/firepace-state || { printf 'STATE:'; cat /tmp/firepace-state; }")
                        if "STATE:" in result:
                            line = result.split("STATE:",1)[1].splitlines()[0].strip()
                            if line:
                                try: self.timer.update(json.loads(line))
                                except ValueError: pass
                    elif APP == "light-kwriter":
                        self.command(":")
                self.wake.wait(0.1 if frame else 0.8)
                self.wake.clear()
            except (OSError, ConnectionError, RuntimeError) as error:
                with self.lock:
                    self.close()
                    if frame:
                        if self.pending is None: self.pending = frame
                    self.message = "Pair Wi-Fi over USB first" if "Pair Wi-Fi" in str(error) else "Unplugged · reconnecting"
                time.sleep(1)

kindle = Kindle()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

    def log_message(self, *args):
        pass

    def json(self, value, code=200):
        data = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def valid_host(self):
        port = self.server.server_port
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def do_GET(self):
        if not self.valid_host():
            self.json({"error": "Use localhost"},403)
            return
        if self.path == "/api/state":
            self.json({"connected": kindle.connected, "enabled": kindle.enabled, "message": kindle.message, "latency": kindle.latency, "timer": kindle.timer, "transport": kindle.transport})
        elif self.path == "/api/data":
            file = DATA / "data.json"
            self.json(json.loads(file.read_text()) if file.exists() else {})
        else:
            super().do_GET()

    def do_POST(self):
        if not self.valid_host():
            self.json({"error": "Use localhost"},403)
            return
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            self.json({"error": "Use the local app page"}, 403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 4_000_000 or self.headers.get_content_type() != "application/json":
                raise ValueError("Unsupported request")
            data = json.loads(self.rfile.read(size))
            if self.path == "/api/save":
                temp = DATA / "data.tmp"
                temp.write_text(json.dumps(data))
                temp.replace(DATA / "data.json")
            elif self.path == "/api/pair":
                with kindle.lock: kindle.pair_wifi()
            elif self.path == "/api/connect":
                transport = data.get("transport", kindle.transport)
                if transport not in ["usb","wifi"]: raise ValueError("Invalid connection")
                if transport != kindle.transport:
                    with kindle.lock: kindle.close()
                    kindle.transport = transport
                    kindle.auto_config = None
                kindle.enabled = bool(data.get("enabled"))
                if not kindle.enabled:
                    with kindle.lock: kindle.close()
                    kindle.message = "Disconnected · saved locally"
            elif self.path == "/api/frame":
                if data["rotation"] not in [0,1,2,3]: raise ValueError("Invalid rotation")
                image = base64.b64decode(data["image"])
                parts = image.split(b"\n",3)
                if len(parts) != 4 or parts[0] != b"P5" or parts[2] != b"255": raise ValueError("Invalid image")
                width,height = map(int,parts[1].split())
                if (width,height) not in [(800,600),(600,800)] or len(parts[3]) != width*height: raise ValueError("Invalid screen size")
                kindle.pending = data
                kindle.wake.set()
            elif self.path == "/api/timer":
                self.timer_request(data)
            else:
                self.json({"error": "Unknown request"},404)
                return
            self.json({"ok": True})
        except (KeyError, ValueError, OSError, ConnectionError, RuntimeError, subprocess.SubprocessError) as error:
            self.json({"error": str(error)}, 400)

    def timer_request(self, data):
        if APP != "firepace": raise ValueError("Not a timer app")
        action = data.get("action")
        with kindle.lock:
            if not kindle.connected: raise ValueError("Connect your Kindle first")
            if action == "start":
                duration = int(data["seconds"])
                break_seconds = int(data["breakSeconds"])
                if not 1 <= duration <= 86400 or not 1 <= break_seconds <= 86400: raise ValueError("Invalid duration")
                rotation = int(data["rotation"])
                if rotation not in [0,1,2,3]: raise ValueError("Invalid rotation")
                assets = data["assets"]
                kindle.command("test ! -f /tmp/firepace.pid || kill $(cat /tmp/firepace.pid) 2>/dev/null; mkdir -p /mnt/us/firepace/assets")
                for name, encoded in assets.items():
                    if not name.replace("-", "").isalnum(): raise ValueError("Invalid asset")
                    kindle.upload("/mnt/us/firepace/assets/" + name + ".pgm", base64.b64decode(encoded))
                kindle.upload("/mnt/us/firepace/timer.sh", (ROOT / "device" / "timer.sh").read_bytes())
                settings = "DURATION="+str(duration)+"\nBREAK_SECONDS="+str(break_seconds)+"\nROTATION="+str(rotation)+"\nCOUNT_UP="+str(int(bool(data.get("countUp"))))+"\nWIDTH="+str(int(data["width"]))+"\nHEIGHT="+str(int(data["height"]))+"\nDIGIT_WIDTH="+str(int(data["digitWidth"]))+"\nCLOCK_SIZE="+str(int(data["clockSize"]))+"\n"
                kindle.upload("/mnt/us/firepace/settings", settings.encode())
                kindle.command("rm -f /tmp/firepace-action; nohup sh /mnt/us/firepace/timer.sh >/tmp/firepace-log 2>&1 </dev/null &")
                kindle.timer = {"remaining": duration, "phase": "focus", "paused": False, "elapsed": 0}
            elif action in ["pause", "resume", "restart", "skip", "exit", "refresh"]:
                kindle.command("printf '%s' " + shlex.quote(action) + " > /tmp/firepace-action")
            else: raise ValueError("Unknown timer action")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--open", action="store_true")
    options = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", options.port), Handler)
    print("Open http://127.0.0.1:" + str(options.port), flush=True)
    if options.open:
        import webbrowser
        webbrowser.open("http://127.0.0.1:" + str(options.port))
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        kindle.enabled = False
        with kindle.lock: kindle.close()
        server.server_close()
