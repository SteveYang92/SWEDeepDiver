from abc import ABC, abstractmethod
import os
import shutil
from typing import Any


class IDecryptor(ABC):
    """
    解密器接口，所有具体实现必须覆写 decrypt 方法。
    """

    @abstractmethod
    def decrypt(self, input_file_path: str, output_dir: str, filename: str) -> str:
        """
        解密 input_file_path 指定的文件，并把结果写入 output_dir 目录。

        参数
        ----
        input_file_path : str
            待解密的源文件路径（需保证存在）
        output_dir : str
            输出目录，若不存在会自动创建
        filename : str
            文件名称
        返回
        ----
        str
            解密后文件完整路径（含文件名）
        """
        raise NotImplementedError


class NoOpDecryptor(IDecryptor):
    def decrypt(self, input_file_path, output_dir, filename: str):
        log_path = os.path.join(output_dir, filename)
        shutil.copy2(input_file_path, log_path)
        return log_path
