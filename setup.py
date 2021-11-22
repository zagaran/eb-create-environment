import os
import setuptools


with open(os.path.join(os.path.dirname(__file__), 'README.md')) as readme:
    README = readme.read()

setuptools.setup(
    author="Zagaran, Inc.",
    author_email="info@zagaran.com",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    description="Tool to create an Elastic Beanstalk environment and linked database using sensible defaults",
    entry_points={
        "console_scripts": ["eb-create-environment=eb_create_environment.script:main"],
    },
    install_requires=["boto3", "choicesenum", "ipython", "jedi", "pyyaml"],
    keywords="aws eb elastic beanstalk rds database create environment",
    license="MIT",
    long_description=README,
    long_description_content_type="text/markdown",
    name="eb-create-environment",
    packages=setuptools.find_packages(),
    package_data={'': ['default_config.yml']},
    include_package_data=True,
    python_requires='>=3.6',
    url="https://github.com/zagaran/eb-environment-creation",
    version="0.0.2",
)
