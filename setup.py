from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements/base.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="autodialer-pro",
    version="3.0.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="AutoDialer Pro - система автоматического обзвона для Asterisk",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/naumenis/autodialer-pro",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Telecommunications Industry",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Communications :: Telephony",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "autodialer=autodialer.main:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
