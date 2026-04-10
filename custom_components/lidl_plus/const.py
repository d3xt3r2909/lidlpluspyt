DOMAIN = "lidl_plus"

CONF_REFRESH_TOKEN = "refresh_token"
CONF_LANGUAGE = "language"
CONF_COUNTRY = "country"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

DEFAULT_UPDATE_INTERVAL_HOURS = 24
CONF_UPDATE_INTERVAL = "update_interval_hours"

CONF_ACTIVATION_DAY = "activation_day"
CONF_ACTIVATION_HOUR = "activation_hour"
DEFAULT_ACTIVATION_DAY = 0   # Monday
DEFAULT_ACTIVATION_HOUR = 8  # 08:00

WEEKDAYS = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
    7: "Every day",
}

SENSOR_COUPONS_AVAILABLE = "coupons_available"
SENSOR_COUPONS_ACTIVATED = "coupons_activated"
SENSOR_LAST_RECEIPT_AMOUNT = "last_receipt_amount"
SENSOR_LAST_RECEIPT_DATE = "last_receipt_date"
SENSOR_MONTHLY_SPENDING = "monthly_spending"
