from setuptools import setup, find_packages

setup(
    name="main",
    version="0.0.1",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.68.0",
        "uvicorn>=0.15.0",
        "python-dotenv>=0.19.0",
        "mysqlclient>=2.0.3",
        "redis>=4.0.0",
        "sqlalchemy>=1.4.0",
    ],
)