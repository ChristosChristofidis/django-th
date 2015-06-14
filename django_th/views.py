# coding: utf-8
from __future__ import unicode_literals
from django.shortcuts import render, redirect
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse_lazy, reverse
from django.contrib.auth import logout

from django.views.generic import TemplateView, UpdateView, ListView, DeleteView
from django.db.models import Q
from django.utils.translation import ugettext as _


# trigger_happy
from django_th.models import TriggerService, UserService, ServicesActivated
from django_th.services import default_provider
from django_th.tools import get_service
from django_th.forms.base import TriggerServiceForm

import logging
# Get an instance of a logger
logger = logging.getLogger(__name__)

default_provider.load_services()

"""
   Part I : Trigger Part
"""

# ************************
#  FBV : simple actions  *
# ************************


def logout_view(request):
    """
        logout the user then redirect him to the home page
    """
    logout(request)
    return HttpResponseRedirect(reverse('base'))


def trigger_on_off(request, trigger_id):
    """
        enable/disable the status of the trigger then go back home
        :param trigger_id: the trigger ID to switch the status to True or False
        :type trigger_id: int
    """
    trigger = get_object_or_404(TriggerService, pk=trigger_id)
    if trigger.status:
        title = 'disabled'
        title_trigger = _('Set this trigger on')
        btn = 'success'
        trigger.status = False
    else:
        title = _('Edit your service')
        title_trigger = _('Set this trigger off')
        btn = 'primary'
        trigger.status = True
    trigger.save()

    return render(request, 'triggers/trigger_line.html',
                           {'trigger': trigger,
                            'title': title,
                            'title_trigger': title_trigger,
                            'btn': btn})


def service_related_triggers_switch_to(request, user_service_id, switch):
    """
        switch the status of all the triggers related to the service,
        then go back home
        :param service_id: the service ID to switch the status to
        True or False of all the related trigger
        :type service_id: int
        :param switch: the switch value
        :type switch: string off or on
    """
    status = True
    if switch == 'off':
        status = False

    TriggerService.objects.filter(provider__id=user_service_id).update(
        status=status)
    TriggerService.objects.filter(consumer__id=user_service_id).update(
        status=status)

    return HttpResponseRedirect(reverse('user_services'))


def trigger_switch_all_to(request, switch):
    """
        switch the status of all the triggers then go back home
        :param switch: the switch value
        :type switch: string off or on
    """
    status = True
    if switch == 'off':
        status = False
    triggers = TriggerService.objects.all()
    for trigger in triggers:
        trigger.status = status
        trigger.save()

    return HttpResponseRedirect(reverse('base'))


def list_services(request, step):
    """
        get the activated services added from the administrator
    """
    all_datas = []

    if step == '0':
        services = ServicesActivated.objects.filter(status=1)
    elif step == '3':
        services = ServicesActivated.objects.filter(status=1,
                                                    id__iexact=request.id)
    for class_name in services:
        all_datas.append({class_name: class_name.name.rsplit('Service', 1)[1]})

    return all_datas


def trigger_edit(request, trigger_id, edit_what):
    """
        edit the provider
        :param trigger_id: ID of the trigger to edit
        :param edit_what: edit a 'Provider' or 'Consumer' ?
        :type trigger_id: int
        :type edit_what: string
    """
    if edit_what not in ('Provider', 'Consumer'):
        # bad request
        return redirect('base')

    form_name = edit_what + 'Form'

    # get the trigger object
    service = TriggerService.objects.get(id=trigger_id)

    if edit_what == 'Consumer':
        my_service = service.consumer.name.name
    else:
        my_service = service.provider.name.name

    # get the service name
    service_name = str(my_service).split('Service')[1]
    # get the model of this service
    model = get_service(my_service)

    # get the data of this service linked to that trigger
    data = model.objects.get(trigger_id=trigger_id)

    template = service_name.lower() + '/edit_' + edit_what.lower() + ".html"

    if request.method == 'POST':
        form = get_service(my_service, 'forms', form_name)(request.POST,
                                                           instance=data)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse('trigger_edit_thanks'))
    else:
        form = get_service(my_service, 'forms', form_name)(instance=data)

    context = {'description': service.description, 'edit_what': edit_what}
    return render(request, template, {'form': form, 'context': context})


class TriggerListView(ListView):
    """
        list of Triggers
        the list can be filtered by service
    """
    context_object_name = "triggers_list"
    queryset = TriggerService.objects.all()
    template_name = "home.html"
    paginate_by = 3

    def get_queryset(self):
        filtered_by = None
        # by default, sort by date_created
        ordered_by = (str('-date_created'), )
        # get the Trigger of the connected user
        if self.request.user.is_authenticated():
            # if the user selected a filter, get its ID
            if 'trigger_filtered_by' in self.kwargs:
                filtered_by = UserService.objects.filter(
                    user=self.request.user,
                    name=self.kwargs['trigger_filtered_by'])[0].id

            if 'trigger_ordered_by' in self.kwargs:
                """
                    sort by 'name' property in the related model UserService
                """
                order_by = str(self.kwargs['trigger_ordered_by'] + "__name")
                # append to the tuple, the selected 'trigger_ordered_by'
                # choosen in the dropdown
                ordered_by = (order_by, ) + ordered_by

            # no filter selected
            if filtered_by is None:
                return self.queryset.filter(user=self.request.user).order_by(
                    *ordered_by).select_related('consumer__name',
                                                'provider__name')

            # filter selected : display all related triggers
            else:
                # here the queryset will do :
                # 1) get trigger of the connected user AND
                # 2) get the triggers where the provider OR the consumer match
                # the selected service
                return self.queryset.filter(user=self.request.user).filter(
                    Q(provider=filtered_by) |
                    Q(consumer=filtered_by)).order_by(
                    *ordered_by).select_related('consumer__name',
                                                'provider__name')
        # otherwise return nothing when user is not connected
        return TriggerService.objects.none()

    def get_context_data(self, **kw):
        """
            get the data of the view

            data are :
            1) number of triggers enabled
            2) number of triggers disabled
            3) number of activated services
            4) list of activated services by the connected user
        """
        triggers_enabled = triggers_disabled = services_activated = ()

        context = super(TriggerListView, self).get_context_data(**kw)

        if 'trigger_filtered_by' in self.kwargs:
            page_link = reverse('trigger_filter_by',
                                kwargs={'trigger_filtered_by':
                                        self.kwargs['trigger_filtered_by']})
        elif 'trigger_ordered_by' in self.kwargs:
            page_link = reverse('trigger_order_by',
                                kwargs={'trigger_ordered_by':
                                        self.kwargs['trigger_ordered_by']})
        else:
            page_link = reverse('home')

        if self.request.user.is_authenticated():
            # get the enabled triggers
            triggers_enabled = TriggerService.objects.filter(
                user=self.request.user, status=1).count()
            # get the disabled triggers
            triggers_disabled = TriggerService.objects.filter(
                user=self.request.user, status=0).count()
            # get the activated services
            user_service = UserService.objects.filter(user=self.request.user)
            """
                List of triggers activated by the user
            """
            context['trigger_filter_by'] = user_service
            """
                number of service activated for the current user
            """
            services_activated = user_service.count()

        """
            which triggers are enabled/disabled
        """
        context['nb_triggers'] = {'enabled': triggers_enabled,
                                  'disabled': triggers_disabled}
        """
            Number of services activated
        """
        context['nb_services'] = services_activated

        context['page_link'] = page_link

        return context


class TriggerUpdateView(UpdateView):
    """
        Form to update description
    """
    model = TriggerService
    form_class = TriggerServiceForm
    template_name = "triggers/edit_description_trigger.html"
    success_url = reverse_lazy("trigger_edit_thanks")

    @method_decorator(login_required)
    def dispatch(self, *args, **kwargs):
        return super(TriggerUpdateView, self).dispatch(*args, **kwargs)


class TriggerEditedTemplateView(TemplateView):
    """
        just a simple form to say thanks :P
    """
    template_name = "triggers/thanks_trigger.html"

    def get_context_data(self, **kw):
        context = super(TriggerEditedTemplateView, self).get_context_data(**kw)
        context['sentence'] = 'Your trigger has been successfully modified'
        return context


class TriggerDeleteView(DeleteView):
    """
        page to delete a trigger
    """
    model = TriggerService
    template_name = "triggers/delete_trigger.html"
    success_url = reverse_lazy("trigger_delete_thanks")

    # @method_decorator(login_required)
    def dispatch(self, *args, **kwargs):
        return super(TriggerDeleteView, self).dispatch(*args, **kwargs)


class TriggerDeletedTemplateView(TemplateView):
    """
        just a simple form to say thanks :P
    """
    template_name = "triggers/thanks_trigger.html"

    def get_context_data(self, **kw):
        context = super(TriggerDeletedTemplateView, self).\
            get_context_data(**kw)
        context['sentence'] = 'Your trigger has been successfully deleted'
        return context
