from abc import ABC, abstractmethod


class IDataMasker(ABC):
    """
    数据脱敏器纯接口：str → str
    """

    @abstractmethod
    def mask(self, raw: str) -> str:
        """
        对原始字符串进行脱敏处理，返回脱敏后的字符串。

        参数
        ----
        raw : str
            待脱敏的原始文本

        返回
        ----
        str
            脱敏后的文本
        """
        raise NotImplementedError


class NoOpMasker(IDataMasker):
    """
    空实现：不做任何脱敏，原样返回输入字符串。
    """

    def mask(self, raw: str) -> str:
        return raw
