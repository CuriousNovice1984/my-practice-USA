"""Date and number formats for the practice's US English locale.

Dates are DD MMM YY ("01 Oct 26"): unambiguous between US and European
readers, unlike 10/01/26.
"""

DATE_FORMAT = "d M y"
SHORT_DATE_FORMAT = "d M y"
DATETIME_FORMAT = "d M y, g:i A"
SHORT_DATETIME_FORMAT = "d M y, g:i A"
TIME_FORMAT = "g:i A"
MONTH_DAY_FORMAT = "d M"
YEAR_MONTH_FORMAT = "F Y"
DATE_INPUT_FORMATS = ["%Y-%m-%d", "%d %b %y", "%d %b %Y", "%m/%d/%Y", "%m/%d/%y"]
FIRST_DAY_OF_WEEK = 0  # Sunday
DECIMAL_SEPARATOR = "."
THOUSAND_SEPARATOR = ","
NUMBER_GROUPING = 3
