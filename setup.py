from setuptools import find_packages, setup

import sphinxmix

if __name__ == "__main__":
      
      setup(name='sphinxmix',
            version=sphinxmix.VERSION,
            description='A Python implementation of the Sphinx mix packet format.',
            author='George Danezis',
            author_email='g.danezis@ucl.ac.uk',
            url=r'http://sphinxmix.readthedocs.io/en/latest/',
            packages=find_packages(include=["sphinxmix", "sphinxmix.*", "por", "por.*"]),
            license="2-clause BSD",
            long_description="""A Python implementation of the Sphinx mix packet format.

            For full documentation see: http://sphinxmix.readthedocs.io/en/latest/
            """,

            setup_requires=['pytest-runner', "pytest"],
            tests_require=[
                  "pytest",
                  "future >= 0.14.3",
                  "pytest >= 3.0.0",
                  "msgpack-python >= 0.4.6",
                  "petlib >= 0.0.41",
                  "pynacl >= 1.1.0",
                  "aioquic >= 1.3.0",
            ],
            install_requires=[
                  "future >= 0.14.3",
                  "pytest >= 3.0.0",
                  "msgpack-python >= 0.4.6",
                  "petlib >= 0.0.41",
                  "pynacl >= 1.1.0",
                  "aioquic >= 1.3.0",
            ],
            entry_points={
                  "console_scripts": [
                        "por-relay=por.daemon.relay:main",
                        "por-expert=por.daemon.expert:main",
                        "por-client=por.daemon.client:main",
                        "por-directory=por.daemon.directory:main",
                  ],
            },
      )
