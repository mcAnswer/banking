from django import forms
from apps.midas import models
from django.forms import widgets
from django.contrib.admin.widgets import AdminDateWidget 

class InvoiceForm(forms.ModelForm):
    class Meta:
        model = models.Invoice
        fields = '__all__'
        # widgets = {
        #     'due_date':AdminDateWidget,
        #     'service_date':AdminDateWidget,
        #     'packed_date':AdminDateWidget,
        #     'paid_date':AdminDateWidget,
        #     'accounted_date':AdminDateWidget,
        # }
        #fields = ['', 'text']
        #widgets = {'photo':widgets.HiddenInput,'text':widgets.TextInput}

class TokenForm(forms.Form):
    code = forms.CharField(label='Code', max_length=8, required=False)
