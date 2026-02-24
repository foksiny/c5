from setuptools import setup, find_packages

setup(
    name='c5c',
    version='0.1.0',
    description='C5 Compiler Toolchain',
    author='jose',
    packages=['c5c'],
    entry_points={
        'console_scripts': [
            'c5c=c5c.main:main',
        ],
    },
)
