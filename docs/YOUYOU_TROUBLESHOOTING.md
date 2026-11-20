# YouYouSU-Next 排查手册

本 fork 在上游 KernelSU-Next 的基础上做了这些改动：

- 包名 `com.youyousu.homeyouyou`
- 应用名 `YouYouSU-Next`
- 用自己的密钥签名

本文记录遇到过的问题和排查方法。这个文件只有本 fork 有，合并上游时不会冲突。

## 关键信息速查

| 项目 | 值 / 位置 |
|---|---|
| 自用分支 | `youyou`（基于 `upstream/dev`） |
| 上游远程 | `upstream` = https://github.com/KernelSU-Next/KernelSU-Next |
| 签名密钥 | `~/keys/youyousu-release.jks`，alias `youyousu`，**RSA 2048** |
| 证书 SIZE / HASH | `0x2cf` / `3ba777f7e137c0a3bc0b8da19d32415ba68078d9d2a4ec57d30ad5c965281804` |
| 内核编译脚本 | `~/android_kernel/build_ksu.sh`（通过 `KSU_NEXT_MANAGER_SIZE/HASH` 传入签名） |
| 内核里的 KernelSU | `android_kernel_oneplus_sm8150/KernelSU-Next` 子模块，**legacy** 分支 |
| 计算 jks 证书 | `~/android_kernel/ksu_cert_hash.sh <jks> <alias>` |
| 检查 APK 证书 | `python3 scripts/youyou_apk_cert.py <apk>` |
| CI 发布 | `.github/workflows/youyou-release.yml`：推送 `youyou` 后自动发 Release（tag `youyou-<versionCode>`） |

## 管理器显示"不支持 | 未集成"

意思是内核没有把这个 App 认作管理器。按下面顺序排查。

### 1. 先看内核日志（不需要 root）

```sh
adb bugreport br.zip && unzip -o br.zip
grep -a -E 'KernelSU|susfs' bugreport-*.txt | grep -v -E 'IOCTL|= 0x|setresuid'
```

在 `KERNEL LOG` 段落里找扫描管理器的部分：`Searching manager...` 后面跟着每个 APK 的 `is_manager: 0/1`。

| 日志 | 原因 | 处理 |
|---|---|---|
| 没有 `welcome to KernelSU` | 内核里没有 KernelSU，或者刷错了内核 | 检查刷入的 zip 和 `uname -a` 的编译时间 |
| `cert length overlimit` | 证书超过 **1024 字节**（`CERT_MAX_LENGTH`） | 见第 2 步 |
| 你的 APK 是 `is_manager: 0`，没有其他报错 | 签名 SIZE/HASH 和内核不一致，或者 APK 里有 v3 签名块 | 见第 3、4 步 |
| 根本没扫描到你的 APK | 开机后才安装，没触发重新扫描 | 重启手机 |

### 2. 证书太大（RSA 4096 不能用）

内核写死了证书最大 1024 字节，RSA 4096 的证书大约 1231 字节（`0x4cf`），会被直接拒绝。密钥必须用 **RSA 2048**（或 EC）：

```sh
keytool -genkeypair -keystore ~/keys/youyousu-release.jks -alias youyousu \
  -keyalg RSA -keysize 2048 -validity 36500 -dname "CN=YouYouSU"
~/android_kernel/ksu_cert_hash.sh ~/keys/youyousu-release.jks youyousu   # SIZE 必须 < 0x400
```

换密钥之后，下面几处都要跟着改：

1. 内核 `build_ksu.sh` 的 SIZE/HASH，然后重新编译、刷入
2. GitHub Secret `KEYSTORE`（必要时还有两个密码）
3. 手机上先 `adb uninstall com.youyousu.homeyouyou` 再装新包，因为签名变了不能覆盖安装

### 3. 签名 SIZE/HASH 不一致

```sh
python3 scripts/youyou_apk_cert.py app.apk                        # APK 实际的签名
grep 'Manager signature' ~/android_kernel/out/build.log           # 内核编进去的签名
adb shell uname -a                                                # 确认手机跑的是哪次编译
```

两边必须完全一致。注意：

- 本仓库 `kernel/Kbuild` 里的默认值仍是**上游作者的证书**（`0x3e6` / `79e5…`）。
- CI 里编的 LKM 用的也是这个默认值，所以不认我们的管理器。
- 自己编内核时一定要传 `KSU_NEXT_MANAGER_SIZE/HASH`。

想从手机上取出已安装的 APK 来检查：

```sh
adb pull "$(adb shell pm path com.youyousu.homeyouyou | head -1 | sed 's/package://;s/\r//')" installed.apk
```

### 4. APK 里有 v3 签名块

内核只接受 v2 签名块（`0x7109871a`）和 verity padding（`0x42726577`），**出现其他任何签名块都判为无效**。

- Gradle 编出来的包只有 v2，没有这个问题。
- 手动用 `apksigner` 重签时，默认会加上 v3，必须关掉：

```sh
apksigner sign --ks ~/keys/youyousu-release.jks --ks-key-alias youyousu \
  --v1-signing-enabled false --v2-signing-enabled true \
  --v3-signing-enabled false --v4-signing-enabled false \
  --out out.apk in.apk
python3 scripts/youyou_apk_cert.py out.apk   # 最后一行应该是 kernel check: OK
```

## 管理器提示"Kernel update required"

意思是管理器的 UAPI 版本比内核的高（`managerUAPIVersion > kernelUAPIVersion`）。

- 管理器从 `dev` 分支编译，UAPI 版本见 `kernel/include/uapi/supercall.h` 里的 `KERNEL_SU_UAPI_VERSION`。
- 内核用的是 legacy 分支，UAPI 版本见子模块里的 `uapi/supercall.h`。

处理方法：把内核里的 legacy 子模块更新到上游最新，然后重新编译：

```sh
cd ~/android_kernel/android_kernel_oneplus_sm8150/KernelSU-Next
git fetch origin legacy && git checkout origin/legacy
grep UAPI_VERSION uapi/supercall.h
cd ~/android_kernel && ./build_ksu.sh
```

只换内核、签名没变时，管理器不用重装。

## GitHub Actions

- **Secrets**（Settings → Secrets and variables → **Actions**）：`KEYSTORE`（`base64 -w0 xxx.jks` 的输出）、`KEYSTORE_PASSWORD`、`KEY_ALIAS`、`KEY_PASSWORD`。
  - 密码里不要有单引号：workflow 是用 `echo KEY='...'` 写进 `gradle.properties` 的。
  - 没配 Secrets 时编出来的 APK 不是我们的签名。
- **改了 Secret 后**：在 Actions → **YouYou Release** → Run workflow 新开一次运行。不要用旧运行的 Re-run。
- **版本号相同时**（没有新提交）会覆盖同一个 Release 里的 APK。
- **版本号**来自 `git describe --tags`，已经排除了 `youyou-*` tag。
  - fork 里要有上游的 tag，版本号才是 `v3.4.2-N-gxxxx` 格式；否则只有一串哈希。
  - 推 tag 时一次推全部（`git push origin --tags`）。GitHub 一次收到超过 3 个 tag 时不会触发 workflow，所以上游的 `release.yml` 不会被误触发。

## 同步上游

```sh
git fetch upstream --tags
git switch youyou
git merge upstream/dev          # 解决冲突后 git commit
git push && git push origin --tags
```

合并后要检查的地方：

- **上游新增的文件**如果还在旧包路径 `com/rifsxd/ksunext` 下，要移到 `com/youyousu/homeyouyou`，并替换里面的包名。可以用 `grep -rn 'rifsxd\.ksunext\|rifsxd/ksunext\|rifsxd_ksunext' manager userspace` 检查。
- **上游改了 UAPI 版本**时，内核的 legacy 子模块也要同步更新，参见上一节。
- **`manager/spoof` 脚本**匹配的是 `youyousu`/`homeyouyou`。上游改了这个脚本的话，要保持这一点。
