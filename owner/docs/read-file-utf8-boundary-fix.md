# read_file UTF-8 边界误判 binary 修复

## 问题

`read_file` 工具偶发把 `.py` 等文本文件当作二进制拒绝读取。

## 根因

`ShellFileOperations.read_file` / `read_file_raw` 用 `head -c 1000` 按字节采样文件头部,terminal 后端以 `utf-8, errors="replace"` 解码。当多字节 UTF-8 字符(CJK 3 字节、emoji 4 字节)正好横跨第 1000 字节边界时,残缺尾字节被解码成 `U+FFFD`。

commit `021a07688`(2026-08-01)引入的规则把样本中任何 `U+FFFD` 都当作"真·非法字节"判为 binary,无法区分"文件含非法字节"和"采样器切断合法字符"。结果是合法 UTF-8 文件被误判为二进制,多字节字符越密命中率越高,表现为偶发。

## 方案

`head -c` 的截断伪影只会出现在解码样本的最后一个字符(只切一个字节位,至多一个残缺序列)。据此区分:

1. 样本无 `U+FFFD` -> 原 non-printable ratio 检查。
2. `U+FFFD` 仅出现在末尾 -> 剥离后重新检查;若无残余 `U+FFFD`,视为截断伪影,按文本处理。
3. `U+FFFD` 出现在中部(或剥离尾部后仍有) -> 真·非法字节,判为 binary(保留 021a07688 防 mojibake 意图)。

## 实现方式

运行时 monkey-patch `ShellFileOperations._is_likely_binary`,官方源码零改动。

- 补丁:`owner/patches/file_binary_detection_patch.py`
- 接线:`owner/owner-extensions/__init__.py`(plugin register 时 apply)
- 测试:`tests/owner/patches/test_file_binary_detection_patch.py`

## 残余风险

文件大小约 1000 字节且末尾正好是真·非法字节的极端情况会被误判为文本。概率极低,且下游 read->write 路径有独立的 mojibake 防护,可接受。

## 四场景验证

| 场景 | 修复前 | 修复后 |
|---|---|---|
| ASCII 前缀 + emoji 横跨 byte 1000 | ❌ 误判 binary | ✅ text |
| 中文注释前缀 + emoji 横跨 byte 1000 | ❌ 误判 binary | ✅ text |
| 真·非法字节在窗口中部 | ✅ binary | ✅ binary(不变) |
| GBK 编码老文件 | ✅ binary | ✅ binary(政策保持) |
