from django.contrib import admin
from apps.midas.models import *
# Register your models here.

admin.site.register(Contractor)
admin.site.register(Commitment)
admin.site.register(Invoice)
admin.site.register(Unit)
admin.site.register(ProductInvoiced)
admin.site.register(Session)
