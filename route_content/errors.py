"""赛道汉字内容编排的领域异常。"""


class DomainError(Exception):
    """领域操作被拒绝的基类。"""


class NotFoundError(DomainError):
    """引用的记录不存在。"""


class StateError(DomainError):
    """当前流程状态不允许该操作。"""


class ValidationError(DomainError):
    """资料缺少必要依据或违反编排约束。"""
