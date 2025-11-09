#!/usr/bin/env python3
import os
import time
import fcntl
import boto3
from datetime import datetime
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

VersionCleaner = 1.0
class FileConfig:
    """
    Конфигурация для каждого лог-файла.
    """
    def __init__(
        self,
        path: str,
        clean: bool = True,
        delete: bool = False,
        upload_to_s3: bool = False,
        s3_prefix: str = ""
    ):
        """
        path — путь к лог-файлу
        clean — очистить файл после загрузки
        delete — удалить файл после загрузки
        upload_to_s3 — загружать ли в S3
        s3_prefix — папка (префикс) внутри бакета S3, например "logs/ha/"
        """
        self.path = path
        self.clean = clean
        self.delete = delete
        self.upload_to_s3 = upload_to_s3
        # убираем начальный и конечный слэш, чтобы корректно соединять пути
        self.s3_prefix = s3_prefix.strip("/")


class LogCleaner:
    def __init__(self, files_config: list[FileConfig], wait_timeout: int = 60):
        self.files_config = files_config
        self.wait_timeout = wait_timeout

        # Настройки S3 берём из .env
        self.s3_bucket = os.getenv("S3_BUCKET")
        s3_endpoint = os.getenv("S3_ENDPOINT")
        s3_access_key = os.getenv("S3_ACCESS_KEY")
        s3_secret_key = os.getenv("S3_SECRET_KEY")

        if self.s3_bucket and s3_endpoint and s3_access_key and s3_secret_key:
            self.s3_client = boto3.client(
                "s3",
                endpoint_url=s3_endpoint,
                aws_access_key_id=s3_access_key,
                aws_secret_access_key=s3_secret_key
            )
        else:
            self.s3_client = None

    def upload_to_s3(self, file_path: str, prefix: str = ""):
        """Загрузка файла в S3 в указанную папку, с добавлением timestamp."""
        if not self.s3_client or not self.s3_bucket:
            print(f"[WARN] S3 не настроен, пропускаем загрузку {file_path}")
            return

        if not os.path.exists(file_path):
            print(f"[WARN] Файл {file_path} не найден, пропускаем загрузку.")
            return

        # Формируем имя объекта S3
        base_name = os.path.basename(file_path)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        if prefix:
            key = f"{prefix}/{base_name}-{timestamp}"
        else:
            key = f"{base_name}-{timestamp}"

        try:
            self.s3_client.upload_file(file_path, self.s3_bucket, key)
            print(f"[OK] Файл {file_path} загружен в S3 как s3://{self.s3_bucket}/{key}")
        except Exception as e:
            print(f"[ERROR] Не удалось загрузить {file_path} в S3: {e}")

    def is_file_locked(self, path: str) -> bool:
        """Проверяет, занят ли файл другим процессом."""
        try:
            with open(path, "a") as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                return False
        except (IOError, OSError):
            return True

    def clean_or_delete(self, cfg: FileConfig):
        """Основная логика очистки или удаления файла."""
        if not os.path.exists(cfg.path):
            print(f"[INFO] Файл {cfg.path} не найден, пропускаем.")
            return

        print(f"[INFO] Работа с файлом {cfg.path}")

        start = time.time()
        while self.is_file_locked(cfg.path):
            if time.time() - start > self.wait_timeout:
                print(f"[WARN] Файл {cfg.path} заблокирован дольше {self.wait_timeout} сек, пропускаем.")
                return
            print(f"[WAIT] Файл {cfg.path} занят, ждем...")
            time.sleep(5)

        # Загрузка в S3, если включено
        if cfg.upload_to_s3:
            self.upload_to_s3(cfg.path, cfg.s3_prefix)

        # Очистка или удаление
        try:
            if cfg.delete:
                os.remove(cfg.path)
                print(f"[OK] Файл {cfg.path} удален.")
            elif cfg.clean:
                open(cfg.path, "w").close()
                print(f"[OK] Файл {cfg.path} очищен.")
        except Exception as e:
            print(f"[ERROR] Ошибка при обработке {cfg.path}: {e}")

    def run(self):
        for cfg in self.files_config:
            self.clean_or_delete(cfg)


if __name__ == "__main__":
    # Конфигурации
    configs = [
        FileConfig(
            "/opt/bot/bot_master.log",
            clean=True,
            delete=False,
            upload_to_s3=True,
            s3_prefix="logs/bot_master"
        ),
        FileConfig(
            "/opt/bot/bot_master.systemd.log",
            clean=True,
            delete=False,
            upload_to_s3=False,
        ),
        FileConfig(
            "/opt/bot/bot_master.systemd.err",
            clean=True,
            delete=False,
            upload_to_s3=False,
        ),
    ]

    cleaner = LogCleaner(files_config=configs)
    cleaner.run()
