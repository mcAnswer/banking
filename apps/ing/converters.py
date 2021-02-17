class FourDigitConverter:
    regex = '[0-9]{4}'

    def to_python(self, value):
        return int(value)
    
    def to_url(self, value):
        return '%04d' % value
    
class HexStringConverter:
    regex = '[A-F0-9]+'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value
