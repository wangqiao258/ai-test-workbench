"""新密码的规则检查（纯规则，无 IO、不依赖 Flask）。

为什么单独一个模块：改密码的失败原因必须能**逐条区分**。改造前服务端用
一句话盖住三种原因（"原密码错误或新密码太短"），用户不知道该改哪一项；
这里把每条规则和一个文案绑死，调用方只负责把文案 flash 出去。

规则顺序是刻意的：先查格式（用户自己的输入问题），再查"与原密码相同"，
最后才查黑名单。否则把原密码原样填回去时会报"过于常见"，误导用户。
"""

MIN_LEN = 8
MAX_LEN = 128

# 只收录最常见的几个，不追求全量字典：本平台是内网单用户工具，做字典攻击
# 防护没有意义，真正要拦的是"改完还是默认口令"这类自欺欺人的操作。
WEAK = {
    "admin123", "admin1234", "admin888", "admin123456",
    "12345678", "123456789", "1234567890", "87654321",
    "password", "passw0rd", "p@ssw0rd", "password1",
    "qwerty123", "abc123456", "a1234567", "1qaz2wsx",
    "11111111", "88888888", "iloveyou", "test1234",
}


def check_new_password(new, old=""):
    """检查新密码，返回错误文案；合规返回 None。

    文案即接口，测试按文案断言，改文案要同步改测试。

    这里故意**不**检查"是否等于用户名"：用户名只有 admin（5 位），永远先撞
    长度下限，那条规则在本平台不可达。按"没有来源也没有消费者就别写"的口径
    不留死代码；哪天用户名能改长了再加。
    """
    if new != new.strip():
        return "新密码不能以空格开头或结尾"
    if len(new) < MIN_LEN:
        return f"新密码至少 {MIN_LEN} 位"
    if len(new) > MAX_LEN:
        return f"新密码最多 {MAX_LEN} 位"
    if not any(c.isascii() and c.isalpha() for c in new) \
            or not any(c.isdigit() for c in new):
        return "新密码需同时包含字母和数字"
    if old and new == old:
        return "新密码不能与原密码相同"
    if new.lower() in WEAK:
        return "该密码过于常见，请换一个"
    return None


def hint():
    """给页面用的规则提示。放在这里，改规则时页面文案跟着变。"""
    return f"至少 {MIN_LEN} 位，需同时包含字母和数字"
