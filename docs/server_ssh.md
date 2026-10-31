# 服务器 SSH 连接说明

供本仓库 Agent 和开发者使用。2026-10-30 13:40（Asia/Shanghai）已使用用户提供的密码成功登录，并执行只读命令，退出码为 `0`。

## 连接参数与实测结果

| 项目 | 值 |
| --- | --- |
| 地址 | `10.176.30.103`（需要内网可达） |
| SSH 端口 | `20024` |
| 用户名 | `root` |
| 认证方式 | 密码；本次验证未使用 SSH 密钥或 ssh-agent |
| 远端 `whoami` | `root` |
| 远端主机名 | `70df76a8acf0` |
| 登录工作目录 | `/root` |
| 系统 | Ubuntu 24.04.5 LTS |
| 内核与架构 | `Linux 5.15.0-171-generic aarch64` |
| Python 3 | `/usr/bin/python3` |

以上是登录时的环境快照；后续工作应按需重新检查。SSH 端口与模型 API 的 `20027` 端口不同，SSH 密码也不是模型 API Key；API 接入见 [模型服务说明](qwen38_server_api.md)。

## 本地凭据

用户提供的密码已保存到本机文件：

```text
F:/Personal/Code/A_B/.env.ssh.local
```

该文件包含 `AB_SSH_HOST`、`AB_SSH_PORT`、`AB_SSH_USER`、`AB_SSH_PASSWORD` 四个字段，已被现有 `.gitignore` 的 `.env.*` 规则忽略，不随仓库克隆或推送。读取时把内容当作数据，不要执行文件或将密码打印到日志。

同一台机器的其他 Agent / 工作树可复用此绝对路径。其他机器应自行准备同格式的本地文件，下面的自动化示例可通过进程环境变量 `AB_SSH_ENV_FILE` 指向它。如果凭据文件缺失或认证失败，再向用户确认有效凭据。

## 主机公钥

首次成功登录时采集到的 ED25519 主机公钥已保存在 [configs/server_ssh_known_hosts](../configs/server_ssh_known_hosts)，指纹为：

```text
SHA256:09XX6tzcK/Uwklvs85hmqJD0Xfn/J5cQHT3lfMRtnZY
```

这是首次连接时记录的公钥，未通过独立渠道核验。后续连接固定使用该公钥；若发生不匹配，应先核实服务器是否重建或地址是否变更，再更新记录。

## 交互式登录

用户提供的基本命令：

```powershell
ssh root@10.176.30.103 -p 20024
```

在仓库根目录中，可使用已记录的公钥严格核验后登录，按提示输入本地凭据文件中的密码：

```powershell
ssh -o UserKnownHostsFile=configs/server_ssh_known_hosts -o StrictHostKeyChecking=yes -p 20024 root@10.176.30.103
```

## Agent 无交互连接检查

在仓库根目录的 PowerShell 中运行以下完整代码块。当前机器的 `python`（`D:/Users/hp/anaconda3/python.exe`）已安装 `paramiko`，可直接使用；项目 `.venv` 中未验证此依赖。代码只读取凭据、校验固定公钥并执行四条只读命令，不打印密码。

```powershell
@'
import os
from pathlib import Path

import paramiko

secret_file = Path(os.environ.get(
    "AB_SSH_ENV_FILE", "F:/Personal/Code/A_B/.env.ssh.local"
))
settings = {}
for raw_line in secret_file.read_text(encoding="utf-8-sig").splitlines():
    if not raw_line.strip() or raw_line.lstrip().startswith("#"):
        continue
    name, value = raw_line.split("=", 1)
    settings[name.strip()] = value

client = paramiko.SSHClient()
client.load_host_keys("configs/server_ssh_known_hosts")
client.set_missing_host_key_policy(paramiko.RejectPolicy())
try:
    client.connect(
        hostname=settings["AB_SSH_HOST"],
        port=int(settings["AB_SSH_PORT"]),
        username=settings["AB_SSH_USER"],
        password=settings["AB_SSH_PASSWORD"],
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
        look_for_keys=False,
        allow_agent=False,
    )
    stdin, stdout, stderr = client.exec_command(
        "whoami; hostname; pwd; uname -srm", timeout=20
    )
    stdin.close()
    print(stdout.read().decode("utf-8", errors="replace"), end="")
    print(stderr.read().decode("utf-8", errors="replace"), end="")
    exit_code = stdout.channel.recv_exit_status()
    print(f"remote_exit_status={exit_code}")
    raise SystemExit(exit_code)
finally:
    client.close()
'@ | python -
```

后续任务可按需要替换 `exec_command` 中的远端命令；非交互命令的工作目录应显式指定，例如 `cd /目标目录 && ...`。远端是 ARM64（`aarch64`），选择二进制或环境依赖时应匹配该架构。
