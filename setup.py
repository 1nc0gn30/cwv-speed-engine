#!/usr/bin/env python3
"""Setup configuration for cwv-speed-engine."""

from setuptools import setup, find_packages

setup(
    name="cwv-speed-engine",
    version="1.0.0",
    description="High-performance Core Web Vitals audit engine, optimizer, and MCP server with zero runtime dependencies.",
    long_description=open("README.md", "r", encoding="utf-8").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="CWV Speed Engine Team",
    license="MIT",
    python_requires=">=3.8",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    entry_points={
        "console_scripts": [
            "cwv-engine=cwv_speed_engine.cli:main",
            "speed-engine=cwv_speed_engine.cli:main",
            "cwv-mcp=cwv_speed_engine.mcp_server:main",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
)
