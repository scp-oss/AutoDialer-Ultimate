#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutoDialer Ultimate - Setup Script
Version: 3.0.0
Enterprise-grade auto dialer system

This file allows installation as a Python package:
    pip install -e .
    python setup.py install
"""

import os
import re
from setuptools import setup, find_packages


# =============================================
# Read Version from __init__.py
# =============================================
def read_version():
    """Read version from backend/__init__.py"""
    version_file = os.path.join(
        os.path.dirname(__file__),
        'backend',
        '__init__.py'
    )
    
    if os.path.exists(version_file):
        with open(version_file, 'r', encoding='utf-8') as f:
            content = f.read()
            version_match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", content)
            if version_match:
                return version_match.group(1)
    
    return '3.0.0'


# =============================================
# Read README.md for Long Description
# =============================================
def read_readme():
    """Read README.md for long description"""
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    return 'AutoDialer Ultimate - Enterprise-grade auto dialer system'


# =============================================
# Read Requirements
# =============================================
def read_requirements(filename='requirements.txt'):
    """Read requirements from file"""
    req_path = os.path.join(os.path.dirname(__file__), 'backend', filename)
    
    if os.path.exists(req_path):
        with open(req_path, 'r', encoding='utf-8') as f:
            return [
                line.strip()
                for line in f.readlines()
                if line.strip() and not line.startswith('#')
            ]
    
    # Fallback requirements
    return [
        'fastapi>=0.115.0',
        'uvicorn[standard]>=0.34.0',
        'pydantic>=2.10.0',
        'pydantic-settings>=2.7.0',
        'asyncpg>=0.30.0',
        'sqlalchemy>=2.0.0',
        'redis>=5.2.0',
        'panoramisk>=0.2.0',
        'python-jose[cryptography]>=3.3.0',
        'passlib[bcrypt]>=1.7.4',
        'bcrypt>=4.2.0',
        'python-multipart>=0.0.20',
        'gunicorn>=23.0.0',
        'prometheus-client>=0.21.0',
        'cachetools>=5.5.0',
        'tenacity>=9.0.0',
        'aiofiles>=24.1.0',
    ]


# =============================================
# Read Development Requirements
# =============================================
def read_dev_requirements():
    """Read development requirements"""
    dev_req_path = os.path.join(
        os.path.dirname(__file__),
        'requirements',
        'dev.txt'
    )
    
    if os.path.exists(dev_req_path):
        with open(dev_req_path, 'r', encoding='utf-8') as f:
            return [
                line.strip()
                for line in f.readlines()
                if line.strip() and not line.startswith('#')
            ]
    
    return [
        'pytest>=8.0.0',
        'pytest-asyncio>=0.23.0',
        'pytest-cov>=5.0.0',
        'pytest-mock>=3.12.0',
        'black>=24.0.0',
        'flake8>=7.0.0',
        'mypy>=1.8.0',
        'isort>=5.13.0',
        'pre-commit>=3.6.0',
        'httpx>=0.28.0',
        'faker>=25.0.0',
        'factory-boy>=3.3.0',
        'watchfiles>=1.0.0',
        'ipython>=8.20.0',
        'ipdb>=0.13.13',
    ]


# =============================================
# Package Metadata
# =============================================
VERSION = read_version()
README = read_readme()
INSTALL_REQUIRES = read_requirements()
EXTRAS_REQUIRE = {
    'dev': read_dev_requirements(),
    'test': [
        'pytest>=8.0.0',
        'pytest-asyncio>=0.23.0',
        'pytest-cov>=5.0.0',
        'pytest-mock>=3.12.0',
        'httpx>=0.28.0',
        'faker>=25.0.0',
    ],
    'docs': [
        'sphinx>=7.0.0',
        'sphinx-rtd-theme>=2.0.0',
        'myst-parser>=3.0.0',
    ],
    'monitoring': [
        'prometheus-client>=0.21.0',
        'opentelemetry-api>=1.20.0',
        'opentelemetry-sdk>=1.20.0',
        'opentelemetry-instrumentation-fastapi>=0.41b0',
    ],
    'all': [
        'pytest>=8.0.0',
        'pytest-asyncio>=0.23.0',
        'pytest-cov>=5.0.0',
        'black>=24.0.0',
        'flake8>=7.0.0',
        'sphinx>=7.0.0',
        'sphinx-rtd-theme>=2.0.0',
        'prometheus-client>=0.21.0',
        'opentelemetry-api>=1.20.0',
        'opentelemetry-sdk>=1.20.0',
        'opentelemetry-instrumentation-fastapi>=0.41b0',
    ],
}


# =============================================
# Setup
# =============================================
setup(
    # =========================================
    # Basic Information
    # =========================================
    name='autodialer-ultimate',
    version=VERSION,
    description='Enterprise-grade auto dialer system with Asterisk integration',
    long_description=README,
    long_description_content_type='text/markdown',
    
    # =========================================
    # Author & License
    # =========================================
    author='AutoDialer Team',
    author_email='support@autodialer.local',
    url='https://github.com/naumenis-code/AutoDialer-Ultimate',
    license='MIT',
    
    # =========================================
    # Package Structure
    # =========================================
    packages=find_packages(where='backend', include=['*'], exclude=['tests', 'tests.*']),
    package_dir={'': 'backend'},
    include_package_data=True,
    
    # =========================================
    # Python Version
    # =========================================
    python_requires='>=3.11,<4.0',
    
    # =========================================
    # Dependencies
    # =========================================
    install_requires=INSTALL_REQUIRES,
    extras_require=EXTRAS_REQUIRE,
    
    # =========================================
    # Entry Points (CLI Commands)
    # =========================================
    entry_points={
        'console_scripts': [
            # Main application
            'autodialer=main:app',
            'autodialer-server=main:run_server',
            
            # Management commands
            'autodialer-db=scripts.manage_db:main',
            'autodialer-user=scripts.manage_users:main',
            'autodialer-tts=scripts.tts_helper:main',
            
            # Development server
            'autodialer-dev=main:run_dev',
        ],
    },
    
    # =========================================
    # Classifiers
    # =========================================
    classifiers=[
        # Development Status
        'Development Status :: 5 - Production/Stable',
        
        # Intended Audience
        'Intended Audience :: Telecommunications Industry',
        'Intended Audience :: System Administrators',
        'Intended Audience :: Developers',
        
        # License
        'License :: OSI Approved :: MIT License',
        
        # Operating System
        'Operating System :: POSIX :: Linux',
        'Operating System :: Unix',
        
        # Programming Language
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        
        # Framework
        'Framework :: FastAPI',
        'Framework :: AsyncIO',
        
        # Topic
        'Topic :: Communications :: Telephony',
        'Topic :: Internet :: WWW/HTTP :: HTTP Servers',
        'Topic :: System :: Networking',
        'Topic :: System :: Systems Administration',
        
        # Environment
        'Environment :: Console',
        'Environment :: Web Environment',
        'Environment :: No Input/Output (Daemon)',
        
        # Language
        'Natural Language :: English',
        'Natural Language :: Russian',
    ],
    
    # =========================================
    # Keywords
    # =========================================
    keywords=[
        'asterisk',
        'autodialer',
        'dialer',
        'telephony',
        'voip',
        'sip',
        'pjsip',
        'fastapi',
        'call-center',
        'predictive-dialer',
        'auto-dialer',
        'voice-broadcasting',
        'ivr',
        'tts',
        'text-to-speech',
        'freepbx',
        'ami',
        'asterisk-manager',
    ],
    
    # =========================================
    # Project URLs
    # =========================================
    project_urls={
        'Documentation': 'https://github.com/naumenis-code/AutoDialer-Ultimate/wiki',
        'Source': 'https://github.com/naumenis-code/AutoDialer-Ultimate',
        'Issues': 'https://github.com/naumenis-code/AutoDialer-Ultimate/issues',
        'Discussions': 'https://github.com/naumenis-code/AutoDialer-Ultimate/discussions',
        'Changelog': 'https://github.com/naumenis-code/AutoDialer-Ultimate/blob/main/CHANGELOG.md',
        'Funding': 'https://github.com/sponsors/naumenis-code',
    },
    
    # =========================================
    # Package Data
    # =========================================
    package_data={
        '': [
            '*.conf',
            '*.example',
            '*.template',
            '*.sql',
            '*.sh',
            '*.html',
            '*.css',
            '*.js',
        ],
    },
    exclude_package_data={
        '': [
            '*.pyc',
            '__pycache__',
            '.git',
            '.env',
            '*.log',
            '*.pid',
        ],
    },
    
    # =========================================
    # Data Files (System-wide)
    # =========================================
    data_files=[
        # Configuration examples
        ('/opt/autodialer/config', [
            '.env.example',
        ]),
        # Systemd service files
        ('/etc/systemd/system', [
            'systemd/autodialer.service',
        ]),
        # Documentation
        ('/opt/autodialer/docs', [
            'docs/INSTALL.md',
            'docs/CONFIGURATION.md',
            'docs/API.md',
            'docs/FAQ.md',
        ]),
    ],
    
    # =========================================
    # Scripts (Standalone executables)
    # =========================================
    scripts=[
        'scripts/autodialer-status',
        'scripts/autodialer-restart',
        'scripts/autodialer-logs',
        'scripts/autodialer-tts',
        'scripts/autodialer-redis-status',
        'scripts/autodialer-firewall-status',
        'scripts/autodialer-fail2ban-status',
        'scripts/autodialer-logrotate-status',
    ],
    
    # =========================================
    # Zip Safe
    # =========================================
    zip_safe=False,
)
