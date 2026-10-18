from django.apps import AppConfig


class CollectionsConfig(AppConfig):
    name = "apps.collections"
    label = "user_collections"  # avoid clashing with the stdlib module name in app labels
