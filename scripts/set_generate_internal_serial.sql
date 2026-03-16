-- Set custom_generate_internal_serial = 1 for all Items that have has_serial_no = 1.
-- Run against the ERPNext site database, e.g.:
--   bench --site erpnext.cyberia-tech.ch mariadb < apps/mfr_serial_map/scripts/set_generate_internal_serial.sql

SET SQL_SAFE_UPDATES = 0;

UPDATE `tabItem` SET     `custom_generate_internal_serial` = 1,     `modified` = NOW() WHERE `has_serial_no` = 1 AND `custom_generate_internal_serial` = 0;

SET SQL_SAFE_UPDATES = 1;

SELECT    name,    has_serial_no,    custom_generate_internal_serial FROM `tabItem` WHERE has_serial_no = 1 ORDER BY name;