# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

PACKAGE_NAME = 'pyhx870'
PACKAGE_VERSION = '0.1.0a'

INSTALL_REQUIRES = [
    'coloredlogs',
    'ipython',
    'pyserial',
    'pyusb'
]

TESTS_REQUIRE = [
    'coverage',
    'mock',
    'pytest'
]

DEV_REQUIRES = [
    'coverage',
    'mock',
    'pycodestyle',
    'pytest'
]

setup(
    name=PACKAGE_NAME,
    version=PACKAGE_VERSION,
    description='Tool for Yaesu HX870 flashing and configuration',
    classifiers=[
        'Environment :: Console',
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Intended Audience :: Customer Service',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Natural Language :: English',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Communications :: Ham Radio'
    ],
    keywords=['hamradio', 'radio', 'maritime', 'yaesu', 'standard horizon', 'hx870', 'hx870e', 'firmware', 'flashing'],
    author='Christiane Ruetten',
    author_email='cr@23bit.net',
    url='https://github.com/cr/pyhx870',
    download_url='https://github.com/cr/pyhx870/archive/latest.tar.gz',
    license='GPLv3',
    packages=find_packages(exclude=["tests"]),
    include_package_data=True,  # See MANIFEST.in
    zip_safe=True,
    use_2to3=False,
    install_requires=INSTALL_REQUIRES,
    tests_require=TESTS_REQUIRE,
    extras_require={'dev': DEV_REQUIRES},  # For `pip install -e .[dev]`
    test_suite='nose.collector',
    entry_points={
        'console_scripts': [
            'hx870 = pyhx870.main:main'
        ]
    }
)
