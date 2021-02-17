import os
from PIL import Image as PImage
from mcanswer.settings import MEDIA_ROOT
from os.path import join as pjoin
from tempfile import NamedTemporaryFile
from django.db import models
from django.contrib.auth.models import User
from django.core import validators 
from django.core.files import File
import datetime

def make_elixir(date,amount,sender,receiver,reference,ptype):
    return '{t:03d},{d.year:04d}{d.month:02d}{d.day:02d},{a:d},{br},0,"{ir}","{ii}","{ar}","{ai}",0,{bi},"{r}","","","{v:02d}",'.format(
        t = 120 if ptype == Invoice.ZUS else 110,
        d = date,                 #date of transfer
        a = int(amount*100),      #amount to transfer
        br = sender.iban[2:10],   #bank of recipient
        bi = receiver.iban[2:10], #bank of issuer
        ir = sender.iban,         #iban of recipient
        ii = receiver.iban,       #iban of issuer
        ar = sender.elixir(),     #address of recipient
        ai = receiver.elixir(),   #address of issuer
        r = reference,            #reference
        v = 71 if ptype == Invoice.US else 51,
    )

# Create your models here.
class Contractor(models.Model):
    lowercase = validators.RegexValidator(r'^[a-z]*$', 'Only lowercase characters are allowed.')
    name = models.CharField(max_length=35)
    name2 = models.CharField(max_length=35,blank=True)
    street = models.CharField(max_length=35,blank=True)
    postal = models.CharField(max_length=6,blank=True)
    city = models.CharField(max_length=28,blank=True)
    accounted = models.BooleanField(default=False)
    friendly_name = models.CharField(max_length=35,blank=True)
    short_name = models.CharField(max_length=10,blank=True,validators=[lowercase])
    iban = models.CharField(max_length=26,blank=True)
    nip = models.CharField(max_length=10,blank=True)
    regon = models.CharField(max_length=9,blank=True)
    notice = models.TextField(blank=True)
    owned = models.BooleanField(default=False)
    context = models.CharField(max_length=1,blank=True)
    class Meta:
        db_table = 'midas.kontrahent'

    def __str__(self):
        return '{}'.format(self.friendly_name if self.friendly_name else self.name)
    def elixir(self):
        return '{}|{}|{}|{} {}'.format(self.name,self.name2,self.street,self.postal,self.city)
    def name_as_list(self):
        name = [self.name]
        if self.name2:
            name.append(self.name2)
        name.append(self.street)
        name.append('{0.postal}{1}{0.city}'.format(self,' ' if self.postal and self.city else ''))
        if not self.name2:
            name.append('')
        return name
        
    def as_issuer_ing_dict(self):
        name = self.name_as_list()
        res = {
            'benefname{}'.format(i+1): name[i]
            for i in range(4)
        }
        res['creacc'] = self.iban
        return res

    def as_recipient_ing_dict(self):
        name = self.name_as_list()
        res = {
            'creditor{}'.format(i+1): name[i]
            for i in range(4)
        }
        res['debacc'] = self.iban
        return res

class Session(models.Model):
    token = models.CharField(max_length=64)
    cookie = models.CharField(max_length=1800)
    buffer_account = models.ForeignKey(Contractor,null=True, on_delete=models.SET_NULL)
    buffer_enabled = models.BooleanField(default=False)
    def eat_cookie(self,cookie,diff=set()):
        oldcookies = {i.partition('=')[0].strip():i.partition('=')[2].strip() for i in self.cookie.split(';')}
        cookies = {i.partition('=')[0].strip():i.partition('=')[2].strip() for i in cookie.split(';')}
        newcookies = []

        known_keys = ['JSESSIONID','TSPD_101','toe','cookiePolicyGDPR','s_fid','pqrsSi','s_cc','cookies_accepted','TS0102d16c_30','sat_track']
        keys = diff.symmetric_difference(known_keys)
        for key in keys:
            if key in cookies:
                newcookies.append((key,cookies[key]))
                if key in oldcookies and oldcookies[key] == cookies[key]:
                    print('Using common value of key {}.'.format(key))
                else:
                    print('Using new value of key {}.'.format(key))
            elif key in oldcookies:
                newcookies.append((key,oldcookies[key]))
                print('Using old value of key {}.'.format(key))
            else:
                print(key,'is missing.')
        self.cookie='; '.join('{}={}'.format(*i) for i in newcookies)
# Using new value of key TS0102d16c_30.
# Using common value of key cookiePolicyGDPR.
# Using old value of key cookies_accepted.
# Using new value of key JSESSIONID.
# Using new value of key s_fid.
# Using common value of key s_cc.
# Using new value of key pqrsSi.
# Using common value of key sat_track.
# Using new value of key TSPD_101.
# Using new value of key toe.

        
class Commitment(models.Model):
    DAYS = 'D'
    MONTHS = 'M'
    YEARS = 'Y'
    INTERVAL_CHOICES = (
        (DAYS, 'day'),
        (MONTHS, 'month'),
        (YEARS, 'year'),
    )
    name = models.CharField(max_length=32)
    beneficiary = models.ForeignKey(Contractor,related_name='owings',related_query_name='owing', on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=8, decimal_places=2,null=True,blank=True)
    date = models.DateField(null=True,blank=True)
    interval = models.PositiveSmallIntegerField(null=True,blank=True)
    interval_unit = models.CharField(max_length=1,choices=INTERVAL_CHOICES,default=DAYS)
    fixed = models.BooleanField(default=False)
    split_payment = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    reference = models.CharField(max_length=107,blank=True,validators=[validators.RegexValidator(regex=r'^[^|]{,35}([|][^|]{,35}){,2}$', message='Invalid format')])
    account_debited = models.ForeignKey(Contractor,related_name='oweds',related_query_name='owed', on_delete=models.PROTECT)
    active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'midas.commitment'

    def __str__(self):
        return '{}'.format(self.name)

class Invoice(models.Model):
    ZUS = 'Z'
    US = 'U'
    STANDARD = 'S'
    PZ = 'P'
    TYPE_CHOICES = (
        (ZUS,'zus'),
        (US,'us'),
        (STANDARD,'standardowy'),
        (PZ, 'polecenie zapłaty'),
    )
    number = models.CharField(max_length=35,blank=True)
    issuer = models.ForeignKey(Contractor,related_name='invoices_issued',related_query_name='invoice_issued', on_delete=models.PROTECT)
    recipient = models.ForeignKey(Contractor,related_name='invoices_received',related_query_name='invoice_received', on_delete=models.PROTECT)
    date = models.DateField()
    service_date = models.DateField(null=True,blank=True)
    due_date =  models.DateField()
    commitment = models.ForeignKey(Commitment,null=True,blank=True, on_delete=models.SET_NULL)
    #products =
    total = models.DecimalField(max_digits=8, decimal_places=2)
    fingerprint = models.CharField(max_length=32,blank=True)
    elixir_ref = models.CharField(max_length=10,blank=True)
    packed_date = models.DateField(null=True,blank=True)
    paid_date = models.DateField(null=True,blank=True)
    accounted_date = models.DateField(null=True,blank=True)
    document = models.FileField(upload_to='documents',null=True,blank=True)
    split_payment = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    transfer_confirmation = models.FileField(upload_to='documents',null=True,blank=True)
    reference = models.CharField(max_length=107,blank=True,validators=[validators.RegexValidator(regex=r'^[^|]{,35}([|][^|]{,35}){,2}$', message='Invalid format')])
    notice = models.CharField(max_length=32,blank=True)
    ptype = models.CharField(max_length=1,choices=TYPE_CHOICES,default=STANDARD)
    class Meta:
        db_table = 'midas.invoice'

    def __str__(self):
        if self.commitment:
            return '{} ({})'.format(self.commitment,self.date)
        else:
            return '{} {} ({})'.format(self.issuer,self.number,self.date)

    def as_elixir(self):
        return make_elixir(
            self.due_date,
            self.total,
            self.recipient,
            self.issuer,
            self.reference+('|' if self.reference and self.ptype==self.STANDARD else '') + ('ref:'+self.elixir_ref if self.ptype==self.STANDARD else ''),
            self.ptype
        )

    def get_reference(self):
        refstr = 'ref:'+self.elixir_ref
        reference = self.reference.split('|')
        if len(reference)==1 and not reference[0].strip():
            reference = []
        if len(reference)<4:
            reference.append(refstr)
        elif len(reference)==4 and len(reference[3])<34-len(refstr):
            reference[3] += ' '+refstr
        else:
            raise AssertionError("Too long reference: "+self.reference)
        return reference
        
    def _as_standard_ing_dict(self, buffer_acc):
        reference = self.get_reference()
        result = {
            'amount':str(self.total),
            'details1':reference[0] if len(reference)>0 else '',
            'details2':reference[1] if len(reference)>1 else '',
            'details3':reference[2] if len(reference)>2 else '',
            'details4':reference[3] if len(reference)>3 else '',
            'typtrn':'S',
        }
        if self.split_payment:
            if not self.issuer.nip:
                raise AssertionError("Split payment without NIP")
            result.update({
                'amountVat': self.split_payment,
                'splitIdc': self.issuer.nip,
                "splitInv": self.number,
                "splitTxt": "",
                "split": "S",
            })
                
        if buffer_acc:
            result['debacc']=buffer_acc.iban
            result.update(self.recipient.as_issuer_ing_dict())
            date = self.due_date - datetime.timedelta(days=1)
        else:
            result['debacc']=self.recipient.iban
            result.update(self.issuer.as_issuer_ing_dict())
            date = self.due_date
        if self.due_date > datetime.date.today():
            result['date']='{0:%Y-%m-%d}'.format(date)
        return result

    def _as_us_ing_dict(self):
        result = {
            'amount':str(self.total),
            'typid':'N', #nip
            'id': self.recipient.nip,
            'sfp': self.issuer.friendly_name,
            'okr': self.reference,
            'txt': '',
        }
        result.update(self.issuer.as_issuer_ing_dict())
        result.update(self.recipient.as_recipient_ing_dict())
        result['date']='{0:%Y-%m-%d}'.format(self.due_date)
            
        return result
        
    def as_ing_dict(self,buffer_acc=None):
        self.elixir_ref = '{:%m%d}-{:02x}'.format(self.due_date, self.pk % 256)
        self.save()
        if self.ptype == Invoice.STANDARD or buffer_acc:
            return self._as_standard_ing_dict(buffer_acc)
        elif self.ptype == Invoice.US:
            return self._as_us_ing_dict()

class Unit(models.Model):
    name = models.CharField(max_length=6,unique=True)
    class Meta:
        db_table = 'midas.unit'

    def __str__(self):
        return '{}'.format(self.name)

class ProductInvoiced(models.Model):
    item = models.PositiveSmallIntegerField()
    invoice = models.ForeignKey(Invoice,related_name='products', related_query_name='product', on_delete=models.CASCADE)
    name = models.CharField(max_length=64)
    quality = models.DecimalField(max_digits=4, decimal_places=2)
    unit = models.ForeignKey(Unit,related_name='+', on_delete=models.CASCADE)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    tax = models.DecimalField(max_digits=4, decimal_places=2)
    class Meta:
        db_table = 'midas.productinvoiced'
        unique_together = ('item','invoice')

    def __str__(self):
        return '{}'.format(self.name)
    
