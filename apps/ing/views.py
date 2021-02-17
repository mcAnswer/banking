from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.views import generic
from django.views.generic.edit import FormView
from django import views
from django.http import HttpResponse
from apps.midas import models, forms
import datetime
import json
import random
import requests
import time

# Create your views here.

# Rejestracja zobowiązań i faktur
# Paczka przelewów
# Potwierdzenia
# Rejestracja pp
# Generowanie zip
# ('number','issuer','recipient','date','due_date','commitment','total','fingerprint','paid_date','packed_date','accounted_date','document','transfer_confirmation','reference','notice')
# ('issuer','recipient','due_date','commitment','total','packed_date','transfer_confirmation','notice')
# ('number','issuer','recipient','date','total','accounted_date','document','transfer_confirmation','notice')

class APIError(Exception):
    def __init__(self,result,code=None):
        self.result=result
        self.message=result['msg'] if 'msg' in result else ''
        self.code=code
    def __str__(self):
        return self.message

class APIHttpError(APIError):
    def __init__(self,code):
        self.message = 'HTTP Error {}'.format(code)
        self.code = code
                 
class TokenConfirmationNeeded(APIError):
    def __init__(self,doc_id,mode):
        self.doc_id = doc_id
        self.mode = mode
        self.message = '{} needs your confirmation'.format(doc_id)

class DueThisMonth(generic.ListView):
    template_name = 'midas/due_list.html'
    context_object_name = 'invoices'

    def get_queryset(self):
        try:
            self.date = datetime.date(2000+int(self.kwargs['date'][:2]),int(self.kwargs['date'][2:]),1)
        except (KeyError,TypeError):
            self.date = datetime.date.today()
        self.invoices = models.Invoice.objects.filter(
            due_date__lt = self.date + datetime.timedelta(days=36),
            paid_date__isnull=True,
        ).order_by('due_date')
        self.commitments = models.Commitment.objects.filter(
            date__lt = self.date + datetime.timedelta(days=36),
            active = True,
        ).order_by('date')

        return self.invoices
        
    def get_context_data(self, **kwargs):
        context = super(DueThisMonth, self).get_context_data(**kwargs)
        context['commitments'] = self.commitments
        context['sum'] = sum(i.total for i in self.invoices if not i.packed_date)
        return context

class AccountLastMonth(generic.ListView):
    template_name = 'midas/accounting_list.html'
    last = datetime.date.today() - datetime.timedelta(days=datetime.date.today().day)
    context_object_name = 'invoices'
    queryset = models.Invoice.objects.filter(
        date__month = last.month,
        date__year = last.year,
    ).order_by('date')

    def get_context_data(self, **kwargs):
        context = super(AccountLastMonth, self).get_context_data(**kwargs)
        context['commitments'] = []
        return context

class INGTransfer(generic.DetailView):
    model = models.Invoice
    template_name = 'midas/invoice_ing_transfer.html'
    
class Confirm(generic.ListView):
    template_name = 'midas/confirming_list.html'
    context_object_name = 'invoices'
    queryset = models.Invoice.objects.filter(
        packed_date__isnull=False,
        paid_date__isnull=True
    ).order_by('elixir_ref')

    def get_context_data(self, **kwargs):
        context = super(Confirm, self).get_context_data(**kwargs)
        context['commitments'] = []
        return context

class Commitment(generic.ListView):
    template_name = 'midas/commitment_list.html'
    context_object_name = 'invoices'
    def get_queryset(self):
        self.invoices = models.Invoice.objects.filter(
            commitment = self.kwargs['commitment_id'],
            ).order_by('due_date')
        return self.invoices
    def get_context_data(self, **kwargs):
        context = super(Commitment, self).get_context_data(**kwargs)
        context['commitment'] = models.Commitment.objects.get(pk=self.kwargs['commitment_id'])
        return context

def confirm_payment(request,invoice_id):
    invoice = models.Invoice.objects.get(pk=invoice_id)
    invoice.paid_date = invoice.due_date
    invoice.save()
    return redirect('midas:confirm')

def month_3(month):
    return ['STY','LUT','MAR','KWI','MAJ','CZE','LIP','SIE','WRZ','PAZ','LIS','GRU'][month-1]

def edit_invoice(request,invoice_id=None):
    if request.method == 'POST':
        form = forms.InvoiceForm(request.POST,request.FILES)
        if form.is_valid():
            form.save()
            return redirect('midas:due_this_month')
    else:
        invoice = models.Invoice.objects.get(pk=invoice_id)
        form = forms.InvoiceForm(initial=invoice)
    return render(request, 'midas/invoice.html', {'form': form})
        

def add_invoice(request,commitment_id=None):
    # if this is a POST request we need to process the form data
    if request.method == 'POST':
        # create a form instance and populate it with data from the request:
        form = forms.InvoiceForm(request.POST,request.FILES)
        # check whether it's valid:
        if form.is_valid():
            if form.cleaned_data['number'] and not form.cleaned_data['reference']:
                form.cleaned_data['reference'] = form.cleaned_data['number']
            form.save()
            commitment = models.Commitment.objects.get(pk=form.cleaned_data['commitment'].pk)
            if commitment.interval_unit == models.Commitment.DAYS:
                commitment.date += datetime.timedelta(days=commitment.interval)
            elif commitment.interval_unit == models.Commitment.MONTHS:
                commitment.date = datetime.date(
                    commitment.date.year + (commitment.date.month + commitment.interval - 1) // 12,
                    (commitment.date.month + commitment.interval - 1) % 12 + 1,
                    commitment.date.day
                )
            elif commitment.interval_unit == models.Commitment.YEARS:
                commitment.date = commitment.date.replace(year=commitment.date.year+commitment.interval)
            else:
                raise AssertionError()
            commitment.packed_date=datetime.date.today()
            commitment.save()
            return redirect('midas:due_this_month')
        # if a GET (or any other method) we'll create a blank form
    else:
        if commitment_id is not None:
            commitment = models.Commitment.objects.get(pk=commitment_id)
            form = forms.InvoiceForm(initial={
                'issuer':commitment.beneficiary.pk,
                'recipient':commitment.account_debited.pk,
                'commitment':commitment.pk,
                'date':datetime.date.today(),
                'service_date':datetime.date.today(),
                'due_date':commitment.date,
                'total':commitment.amount,
                'split_payment':commitment.split_payment,
                'reference': (
                    commitment.reference
                    .replace('%MM',month_3(commitment.date.month))
                    .replace('%M','{:02}'.format(commitment.date.month))
                    .replace('%YYY',str(commitment.date.year))
                    .replace('%Y','{:02}'.format(commitment.date.year%100))
                )
            })
        else:
            form = forms.InvoiceForm(initial={
                'date':datetime.date.today(),
                'service_date':datetime.date.today(),
            })

    return render(request, 'midas/invoice.html', {'form': form})

def get_work(request):
    commitments = models.Commitment.objects.filter(
        date__lt = self.date + datetime.timedelta(days=6),
        active = True,
        ).order_by('date')
    response = HttpResponse(content_type='application/json')
    response.write(str({i.name:str(i.date) for i in commitments})+'\n')

def elixir_this_month(request):
    enddate = datetime.date.today() + datetime.timedelta(days=36)
    try:
        index = models.Invoice.objects.filter(
            elixir_ref__startswith='{:%y%m}'.format(datetime.date.today())
            ).order_by('-elixir_ref')[0].elixir_ref[4:6]
    except IndexError:
        index = 0
    else:
        index = int(index)+1
    invoices = models.Invoice.objects.filter(
        due_date__lt = enddate,
        paid_date__isnull=True,
        elixir_ref__exact='',
    )
    for i in invoices:
        i.elixir_ref = '{:%y%m}{:02d}'.format(datetime.date.today(),index)
        i.packed_date = datetime.date.today()
        index += 1
        i.save()
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="elixir{:%y%m%d}.txt"'.format(datetime.date.today())
    data = '\r\n'.join([i.as_elixir() for i in invoices])
    response.write(data.encode('cp1250'))
    return response

class DetailView(generic.DetailView):
    model = models.Invoice
    template_name = 'midas/invoice_list.html'

class IngApiView(generic.View):
    def mock(self,url,payload):
        class Response:
            def __init__(self,status,data):
                self.status_code=status
                self.data = data
            def json(self):
                return self.data
        if url == 'rengetlogin':
            return Response(200,{'data':{'ctxinfo':{'defctx': 'R', 'setctx': 'T', 'alwctx': 'B', 'curctx': 'R'}},'status': 'OK'})
        if url == 'rensetuserctx':
            return Response(200,{'msg': 'Kontekst użytkownika został zmieniony!', 'code': '16418', 'status': 'OK'})
        if url == 'renpayord':
            if payload['data']['debacc'] == '#FIXME buffer account':
                return Response(200,{"status":"OK","data":{"docId":"D0C0001D","mode":"OK"}})
            else:
                return Response(200,{"status":"OK","data":{"docId":"D0C0001D","mode":"TOKEN"}})
        if url == 'renconfirm':
            return Response(200,{"status":"OK","code":"4","msg":"Przelew został zapisany do późniejszej realizacji"})
        
    def curl(self,url,data={},dry_run=False):
        session = models.Session.objects.first()
        payload=data.copy()
        payload['token']=session.token
        payload['trace']=''
        payload['locale']='PL'
            
        headers = {
            'Referer': 'https://login.ingbank.pl/mojeing/app/',
            'X-Wolf-Protection': str(random.random()),
            'X-Requested-With': 'XMLHttpRequest',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:60.0) Gecko/20100101 Firefox/60.0',
            'Cookie':session.cookie,
        }
        print(
            'curl',
            ' '.join('-H "{}={}"'.format(key,headers[key]) for key in headers),
            '--data "{}"'.format(json.dumps(payload)),
            'https://login.ingbank.pl/mojeing/rest/'+url
        )

        if dry_run:
            response = self.mock(url,payload)
        else:
            response = requests.post(
                'https://login.ingbank.pl/mojeing/rest/'+url,
                json = payload,
                headers=headers
            )
        print('<<<',response.status_code)
        if response.status_code == 200:
            result = response.json()
            if url == 'rengetlogin' and 'data' in result:
                print('<<<',result['data']['ctxinfo'])
            else:
                print('<<<',result)
            if 'status' in result and result['status'] == 'OK':
                print('!!!',url,result['status'],'data' in result,'code' in result)
                return result['data'] if 'data' in result else result
            elif 'status' in result:
                raise APIError(result)
            else:
                print('Warning: no status in '.format(result))
                return result
        else:
            raise APIHttpError(response.status_code)

    def switch_context(self,new_ctx,cur_ctx):
        if new_ctx != cur_ctx:
            result = self.curl('rensetuserctx',{'data':{'ctx':new_ctx}})
            if result['code'] == '16418':
                return new_ctx
            else:
                raise Exception('Error {0[code]} while changing context: {0[msg]}.'.format(result))
        else:
            return cur_ctx
        
    def transfer(self, ing_dict, auto=False, payord='renpayord'):
        result = self.curl(payord,{'data':ing_dict})
        if result['mode'] == 'OK' and auto:
            result = self.curl('renconfirm',{'data':{"docId":result['docId']}})
            return result
        elif auto:
            raise Exception('Buffer error: confirmation {} needed ({}).'.format(
                result['mode'],
                result['msg'] if 'msg' in result else '')
            )
        else:
            raise TokenConfirmationNeeded(result['docId'],result['mode'])


        
class PayTokenView(IngApiView,FormView):
    template_name = 'midas/token.html'
    form_class = forms.TokenForm
    success_url = '/'
    
    def post(self,request,**kwargs):
        invoice = get_object_or_404(models.Invoice,pk=kwargs['invoice_id'])
        data = {"docId":kwargs['doc_id']}
        form = self.form_class(request.POST,request.FILES)
        if form.is_valid():
            if 'code' in form.cleaned_data and form.cleaned_data['code']:
                data['code'] = form.cleaned_data['code']
            try:
                result = self.curl('renconfirm', {'data':data})
            except APIError as ex:
                messages.error(request,'API error {0.code}: {0.message}'.format(ex))
            else:
                # result = self.curl('renconfirm',{'data':{"docId":doc_id}})
                if result['code'] in ("124","2",'3',"4"):
                    messages.success(request, result['msg'])
                    invoice.packed_date = datetime.date.today()
                    if result['code'] in ("124","2",'3'):
                        invoice.paid_date = datetime.date.today()
                    invoice.save()
                else:
                    messages.error(request,'Transfer error {0[code]}: {0[msg]}'.format(result))
            return redirect('midas:due_this_month')

    def get_context_data(self,**kwargs):
        ctx = super(PayTokenView,self).get_context_data(**kwargs)
        ctx['invoice'] = models.Invoice.objects.get(pk=self.kwargs['invoice_id'])
        ctx['mode'] = self.kwargs['mode']
        ctx['doc_id'] = self.kwargs['doc_id']
        return ctx
        
class PayInvoiceView(IngApiView):
    def get(self,request,invoice_id):
        try:
            invoice = get_object_or_404(models.Invoice,pk=invoice_id)
            if invoice.paid_date:
                messages.error(request, 'This invoice has been already paid.')
                return redirect('midas:due_this_month')
            if invoice.packed_date:
                messages.warning(request, 'This invoice has been packed before.') #FIXME check status
            if invoice.total == 0 or not invoice.recipient.iban:
                messages.success(request, 'Payment not requested.')
                invoice.packed_date = datetime.date.today()
                invoice.paid_date = datetime.date.today()
                invoice.save()
                return redirect('midas:due_this_month')
            if invoice.ptype in (models.Invoice.STANDARD, models.Invoice.PZ):
                return self.get_standard(request,invoice)
            if invoice.ptype == models.Invoice.US:
                return self.get_us(request,invoice)
            
        except Exception as ex:
            messages.error(request, str(ex))
            return redirect('midas:due_this_month')

    def get_standard(self, request, invoice):
            result = self.curl('rengetlogin',{})
            ctx = result['ctxinfo']['curctx']
            session = models.Session.objects.first()
            invoice_transfer = invoice.as_ing_dict()
            if session.buffer_account and session.buffer_enabled:
                ctx = self.switch_context(session.buffer_account.context,ctx)
                buffer_transfer = invoice.as_ing_dict(session.buffer_account)
                result = self.transfer(buffer_transfer,True)
                if result['code'] in ("124","2","4"):
                    messages.info(request,result['msg'])
                else:
                    raise Exception('Buffer error {0[code]}: {0[msg]}'.format(result))
                time.sleep(2)
            else:
                messages.warning(request, 'Buffer disabled.')
            if invoice.ptype == models.Invoice.PZ:
                invoice.packed_date = datetime.date.today()
                invoice.paid_date = datetime.date.today()
                invoice.save()
                return redirect('midas:due_this_month')
            ctx = self.switch_context(invoice.recipient.context,ctx)
            try:
                result = self.transfer(invoice_transfer)
            except TokenConfirmationNeeded as ex:
                return redirect(
                    'midas:pay_token',
                    invoice_id=invoice.pk,
                    doc_id = ex.doc_id,
                    mode = ex.mode,
                )

    def get_us(self, request, invoice):
        result = self.curl('rengetlogin',{})
        ctx = result['ctxinfo']['curctx']
        invoice_transfer = invoice.as_ing_dict()
        ctx = self.switch_context(invoice.recipient.context,ctx)
        try:
            result = self.transfer(invoice_transfer, payord='renfispayord')
        except TokenConfirmationNeeded as ex:
            return redirect(
                'midas:pay_token',
                invoice_id=invoice.pk,
                doc_id = ex.doc_id,
                mode = ex.mode,
            )
