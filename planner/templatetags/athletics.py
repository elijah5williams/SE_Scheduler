from django import template

from planner.photos import login_photos as _login_photos

register = template.Library()


@register.simple_tag
def login_photos():
    return _login_photos()
