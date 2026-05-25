# 说出来我都不信：Linux 漏洞第4、第5爆了 / Nginx 也继续爆漏洞

**来源**: 小众软件
**原文链接**: https://meta.appinn.net/t/topic/85796
**字数**: 1678 | **状态**: full

---

原始链接在： 说出来我都不信：Linux 漏洞第4、第5爆了 / Nginx 也继续爆漏洞 - 小众软件


这是今天（2026年5月21日）早上：

这是今天晚上：

也不知道说什么了，直接看吧。

## Linux 第4漏洞：CVE-2026-46333（7.1分）

这是继 Copy Fail（4 月 29 日）、Dirty Frag（5 月 7 日）和 Fragnesia（5 月 13 日）之后，在短短三周内爆出注的第四个 Linux 内核安全问题。

- • Copy Fail：一行代码root：2017年至今的系统漏洞，全中
- • Dirty Frag：麻了：Linux 又爆 Dirty Frag 漏洞：Ubuntu、Debian、Arch、RHEL、WSL2 全中招
- • Fragnesia：又来！14天内第三次 Linux 提权漏洞：一行代码，获得 root 权限｜CVE-2026-46300

现在，是第四次了。

### ssh-keysign-pwn

github.com/0xdeadbeefnetwork/ssh-keysign-pwn

这个漏洞可以让 Linux 普通用户，获得 root 用户的任何文件，比如 root 的私钥。

大致流程：

ssh-keysign 开始退出

↓

进程权限还没完全清理

↓

fd 还活着

↓

mm 已经释放

↓

ptrace 权限检查异常

↓

攻击进程调用 pidfd_getfd()

↓

成功复制 root fd

攻击者能在进程“快死但没死透”的瞬间，把 root fd 偷出来，获取了权限。

而获取了 root 私钥，就完全掌握了服务器管理权。

### 如何解决？

内核已经更新，目前多个发行版本已经更新内核：

- • Ubuntu
- • Debian
- • Fedora
- • Arch Linux
- • AlmaLinux

直接升级到最新即可解决。

## Linux 第 5 漏洞：PinTheft（CVE-2026-43494）

引自 w568w 同学的帖子：https://meta.appinn.net/t/topic/85794/

很新的漏洞，还没有评级。

V12 Security，一家自称「AI 智能代码审计」的公司，于 5 月 19 日晚披露了新的 Linux 内核安全漏洞。

**原理**：Linux RDS（可靠数据报 Socket）模块存在 double-free，导致攻击者可以利用 io_uring 模块去覆写具有 suid 的 Page cache，从而实现本地提权。

描述和一键复现 PoC 页面。

**影响范围：**目前为止的所有启用了 RDS 模块的 Linux 内核（包括最新稳定版 7.0.9）。

**修复版本**：暂无。缓解措施如下：

echo 'install rds /bin/false' | sudo tee -a /etc/modprobe.d/cve-pintheft.conf echo 'install rds_tcp /bin/false' | sudo tee -a /etc/modprobe.d/cve-pintheft.conf sudo rmmod rds_tcp rds

## Nginx 漏洞: nginx-poolslip

Nginx 存在远程代码执行漏洞,该漏洞尚未修复。

1.31.0 就是当前 Nginx 的最新版本啊，前几天刚刚修过的 😭（Nginx 爆高危漏洞：可能已经存在十几年｜CVE-2026-42945）。

大概攻击过程就是可以一个 py 脚本，拿到了服务器的 shell：

发现漏洞的 Nebula 说将在修复后的30天内发布技术分析。

啊，这，啥时候更新啊😭

原文：https://www.appinn.com/linux-nginx-security-chaos/

也不知道说点啥，麻了。
