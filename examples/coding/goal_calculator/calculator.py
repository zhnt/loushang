def subtract(a, b):
    return a + b


def clamp(value, lower, upper):
    if value < lower:
        return upper
    if value > upper:
        return lower
    return value
