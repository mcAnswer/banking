from django.urls import path, register_converter
from apps.midas import views, converters
# Uncomment the next two lines to enable the admin:                                                                                                                       
# from django.contrib import admin                                                                                                                                        
# admin.autodiscover()                                                                                                                                                    

register_converter(converters.FourDigitConverter, 'mmdd')
register_converter(converters.HexStringConverter, 'hex')

app_name = 'midas'

urlpatterns = [
    path('<mmdd:date>/', views.DueThisMonth.as_view(),name='due_this_month'),
    path('', views.DueThisMonth.as_view(),name='due_this_month', kwargs={'date':None}),
    path('account/<mmdd:date>/', views.AccountLastMonth.as_view(),name='account_last_month'),
    path('get_work/', views.get_work),
    path('confirm/', views.Confirm.as_view(),name='confirm'),
    path('commitment/<int:commitment_id>/', views.Commitment.as_view(),name='commitment'),
    path('elixir_this_month/', views.elixir_this_month, name='elixir_this_month'),

    path('confirm_payment/<int:invoice_id>/', views.confirm_payment, name='confirm_payment'),
    path('add_invoice/<int:commitment_id>/', views.add_invoice, name='add_invoice'),
    path('add_invoice/', views.add_invoice, name='add_invoice', kwargs={'commitment_id':None}),
    path('pay_invoice/<int:invoice_id>/',views.PayInvoiceView.as_view(),name='pay_invoice'),
    path('pay_token/<int:invoice_id>/<hex:doc_id>/<str:mode>/',views.PayTokenView.as_view(),name='pay_token'),
    path('edit_invoice/<int:invoice_id>/', views.edit_invoice, name='edit_invoice'),
]
