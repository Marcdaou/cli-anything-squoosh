from setuptools import find_namespace_packages, setup

setup(
    name="cli-anything-squoosh",
    version="2.0.0",
    description="Stateful CLI for Squoosh: compress images with Squoosh's real WASM codecs",
    long_description=open("cli_anything/squoosh/README.md").read(),
    long_description_content_type="text/markdown",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    package_data={"cli_anything.squoosh": ["skills/*.md", "utils/*.mjs"]},
    include_package_data=True,
    python_requires=">=3.9",
    install_requires=["click>=8.0", "prompt_toolkit>=3.0"],
    extras_require={"test": ["pytest>=7"]},
    entry_points={"console_scripts": [
        "cli-anything-squoosh=cli_anything.squoosh.squoosh_cli:main"]},
    classifiers=["Programming Language :: Python :: 3", "Topic :: Multimedia :: Graphics"],
)
