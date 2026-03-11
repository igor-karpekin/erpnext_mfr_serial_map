from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
	name="mfr_serial_map",
	version="0.0.1",
	description="Maps manufacturer serial numbers to ERPNext-generated internal serials",
	author="Cyberia Technologies",
	author_email="info@cyberia-tech.ch",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires,
)
