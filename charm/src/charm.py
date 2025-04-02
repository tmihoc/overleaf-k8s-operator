#!/usr/bin/env python3
# Copyright 2024 Ubuntu
# See LICENSE file for licensing details.

"""Charm the application."""

import logging

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.redis_k8s.v0.redis import RedisRelationCharmEvents, RedisRequires
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer, IngressPerAppReadyEvent

logger = logging.getLogger(__name__)


class OverleafK8sCharm(ops.CharmBase):
    """Charm the application."""

    on = RedisRelationCharmEvents()  # type: ignore

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on["community"].pebble_ready, self._configure_change)

        # Charm events defined in the database requires charm library.
        self.database = DatabaseRequires(self, relation_name="database", database_name="overleaf")
        framework.observe(self.database.on.database_created, self._configure_change)
        self.redis = RedisRequires(self, "redis")
        framework.observe(self.on["redis"].relation_updated, self._configure_change)

        # TODO: Figure out how to tell Traefik what the proper hostname is.
        # Tony now thinks this is in the traefik charm config, not in the
        # overleaf-k8s charm at all. The relation just tells traefik how to
        # reach the overleaf-k8s units, not how to expose them to the world.
        self.ingress = IngressPerAppRequirer(self, port=4000, strip_prefix=True)
        framework.observe(self.ingress.on.ready, self._on_ingress_ready)
        framework.observe(self.ingress.on.revoked, self._on_ingress_revoked)

    def _on_ingress_ready(self, event: IngressPerAppReadyEvent):
        self.unit.set_ports(4000)
        logger.info("This app's ingress URL: %s", event.url)

    def _on_ingress_revoked(self, _):
        logger.info("This app no longer has ingress")

    def _configure_change(self, _: ops.HookEvent):
        """Handle pebble-ready event."""
        # Check if we have all the information we need. If not, this is where
        # the holistic approach makes things easy - we don't need to defer, we
        # just wait for the next event to trigger this same method.
        if not self.model.get_relation("database"):
            logger.info("No relation to the MongoDB database yet.")
            return
        mongo_data = self.get_relation_data()
        if not mongo_data:
            logger.info("MongoDB is still setting up.")
            return
        if not self.model.get_relation("redis"):
            logger.info("No relation to the Redis database yet.")
            return
        if not self.redis.relation_data:
            logger.info("Redis is still setting up.")
            return
        container = self.unit.containers["community"]
        if not container.can_connect():
            logger.info("Pebble not ready yet.")
            return

        # Add initial Pebble config layer using the Pebble API
        container.add_layer("Overleaf service", self._pebble_layer(mongo_data), combine=True)

        # Make Pebble reevaluate its plan, ensuring any services are started if enabled.
        container.replan()
        self.unit.status = ops.ActiveStatus()

    def get_relation_data(self):
        """Get database data from relation.

        Returns:
            Dict: Information needed for setting environment variables.
            Returns default if the relation data is not correctly initialized.
        """
        default = {
            "MONGO_USER": "",
            "MONGO_PASSWORD": "",
            "MONGO_HOST": "",
            "MONGO_PORT": "",
            "MONGO_DB": "",
        }

        if self.model.get_relation("database") is None:
            logger.info("MongoDB integration not set up yet.")
            return default

        relation_id = self.database.relations[0].id
        relation_data = self.database.fetch_relation_data()[relation_id]
        # TODO: remove the next logging line.
        logger.info("Raw relation data (id %s): %r", relation_id, relation_data)

        endpoints = relation_data.get("endpoints", "").split(",")
        if len(endpoints) < 1:
            logger.info("No MongoDB endpoint provided yet.")
            return default

        primary_endpoint = endpoints[0].split(":")
        if len(primary_endpoint) < 2:
            logger.info("Assuming primary endpoint is a plain hostname: %r", primary_endpoint)
            host = primary_endpoint[0]
            port = 27017
        else:
            host = primary_endpoint[0]
            port = primary_endpoint[1]

        data = {
            "MONGO_USER": relation_data.get("username"),
            "MONGO_PASSWORD": relation_data.get("password"),
            "MONGO_HOST": host,
            "MONGO_PORT": port,
            "MONGO_DB": relation_data.get("database"),
        }

        if None in (
            data["MONGO_USER"],
            data["MONGO_PASSWORD"],
            data["MONGO_DB"],
        ):
            return default

        return data

    def _pebble_layer(self, database_settings: dict[str, str]) -> ops.pebble.Layer:
        """Return a dictionary representing a Pebble layer."""
        # The services are in overleaf/server-ce/runit.
        # There's 14 of them.
        # When you look at each, there's a run script.
        # In that script, the relevant lines are the last 3:
        # source /etc/overleaf/env.sh
        # This one holds the common variables.
        # export LISTEN_ADDRESS=127.0.0.1
        # This one holds the variables specific for the service.
        # exec /sbin/setuser www-data /usr/bin/node $NODE_PARAMS /overleaf/services/chat/app.js >> /var/log/overleaf/chat.log 2>&1
        # This one has the user, 'www-data', and the actual command. We copy it without $NODE_PARAMS as that's not necessary for now.
        mongo_uri = f"mongodb://{database_settings['MONGO_USER']}:{database_settings['MONGO_PASSWORD']}@{database_settings['MONGO_HOST']}:{database_settings['MONGO_PORT']}/{database_settings['MONGO_DB']}?replicaSet=mongodb-k8s&authSource=admin"
        # TODO: remove this logging, since it contains a password.
        logger.info("Setting Mongo URI to %r from %r", mongo_uri, database_settings)
        if self.redis.relation_data:
            redis_hostname = self.redis.relation_data.get("hostname")
        else:
            redis_hostname = ""
        common_env = {
            "CHAT_HOST": "127.0.0.1",
            "CLSI_HOST": "127.0.0.1",
            "CONTACTS_HOST": "127.0.0.1",
            "DOCSTORE_HOST": "127.0.0.1",
            "DOCUMENT_UPDATER_HOST": "127.0.0.1",
            "DOCUPDATER_HOST": "127.0.0.1",
            # TODO: this should probably not be disabled, but likely we need
            # to set up a relation to an SMTP server first.
            "EMAIL_CONFIRMATION_DISABLED": "true",
            "FILESTORE_HOST": "127.0.0.1",
            "HISTORY_V1_HOST": "127.0.0.1",
            # For Overleaf, MONGO_ENABLED=true doesn't mean "use MongoDB"; it
            # means that the Overleaf image should use the included MongoDB.
            # For the charm, we want to use MongoDB provided by an integration
            # instead.
            "MONGO_ENABLED": "false",
            "NOTIFICATIONS_HOST": "127.0.0.1",
            "OVERLEAF_LISTEN_IP": "0.0.0.0",
            "OVERLEAF_MONGO_URL": mongo_uri,
            "OVERLEAF_REDIS_HOST": redis_hostname,
            "PROJECT_HISTORY_HOST": "127.0.0.1",
            "REALTIME_HOST": "127.0.0.1",
            # Similar to MONGO_ENABLED, this means "a Redis will be provided",
            # not "don't use Redis".
            "REDIS_ENABLED": "false",
            "SERVER_PRO": "false",
            "SPELLING_HOST": "127.0.0.1",
            "WEB_HOST": "127.0.0.1",
            "WEB_API_HOST": "127.0.0.1",
        }
        # "OVERLEAF_DATA_PATH":"data/overleaf",
        # "REDIS_AOF_PERSISTENCE":"true",
        # "OVERLEAF_APP_NAME":"Our Overleaf Instance",
        # "ENABLED_LINKED_FILE_TYPES":"project_file,project_output_file",
        # "ENABLE_CONVERSIONS":"true",

        # TODO: provide a proper secret.
        session_secret = "foo"

        # TODO: this should perhaps be config?
        web_api_user = "overleaf@example.com"
        # TODO: this should be a generated secret
        web_api_password = "overleaf"

        chat_env = common_env.copy()
        chat_env.update({"LISTEN_ADDRESS": "127.0.0.1"})
        clsi_env = common_env.copy()
        clsi_env.update({"LISTEN_ADDRESS": "127.0.0.1"})
        spelling_env = common_env.copy()
        spelling_env.update({"LISTEN_ADDRESS": "127.0.0.1"})
        contacts_env = common_env.copy()
        contacts_env.update({"LISTEN_ADDRESS": "127.0.0.1"})
        docstore_env = common_env.copy()
        docstore_env.update({"LISTEN_ADDRESS": "127.0.0.1"})
        document_updater_env = common_env.copy()
        document_updater_env.update({"LISTEN_ADDRESS": "127.0.0.1"})
        filestore_env = common_env.copy()
        filestore_env.update({"LISTEN_ADDRESS": "127.0.0.1"})
        # TODO: history_v1 doesn't really need all of what's in common, but does
        # need the Mongo settings.
        history_v1_env = common_env.copy()
        history_v1_env.update({"NODE_CONFIG_DIR": "/overleaf/services/history-v1/config"})
        notifications_env = common_env.copy()
        notifications_env.update({"LISTEN_ADDRESS": "127.0.0.1"})
        project_history_env = common_env.copy()
        project_history_env.update({"LISTEN_ADDRESS": "127.0.0.1"})
        real_time_env = common_env.copy()
        real_time_env.update(
            {"LISTEN_ADDRESS": "127.0.0.1", "OVERLEAF_SESSION_SECRET": session_secret}
        )
        web_api_env = common_env.copy()
        web_api_env.update(
            {
                "LISTEN_ADDRESS": "127.0.0.1",
                "ENABLED_SERVICES": "api",
                "METRICS_APP_NAME": "web-api",
                "OVERLEAF_SESSION_SECRET": session_secret,
                "WEB_API_USER": web_api_user,
                "WEB_API_PASSWORD": web_api_password,
            }
        )
        web_env = common_env.copy()
        web_env.update(
            {
                "LISTEN_ADDRESS": "0.0.0.0",
                "ENABLED_SERVICES": "web",
                "WEB_PORT": "4000",
                "OVERLEAF_SESSION_SECRET": session_secret,
                "WEB_API_USER": web_api_user,
                "WEB_API_PASSWORD": web_api_password,
            }
        )
        pebble_layer: ops.pebble.LayerDict = {
            "summary": "Overleaf service",
            "description": "pebble config layer for Overleaf server",
            "services": {
                "chat": {
                    "override": "replace",
                    "summary": "chat",
                    "command": "/usr/bin/node /overleaf/services/chat/app.js",
                    "startup": "enabled",
                    "environment": chat_env,
                    "user": "www-data",
                },
                "clsi": {
                    "override": "replace",
                    "summary": "clsi",
                    "command": "/usr/bin/node /overleaf/services/clsi/app.js",
                    "startup": "enabled",
                    "environment": clsi_env,
                    "user": "www-data",
                },
                "contacts": {
                    "override": "replace",
                    "summary": "contacts",
                    "command": "/usr/bin/node /overleaf/services/contacts/app.js",
                    "startup": "enabled",
                    "environment": contacts_env,
                    "user": "www-data",
                },
                "docstore": {
                    "override": "replace",
                    "summary": "docstore",
                    "command": "/usr/bin/node /overleaf/services/docstore/app.js",
                    "startup": "enabled",
                    "environment": docstore_env,
                    "user": "www-data",
                },
                "document_updater": {
                    "override": "replace",
                    "summary": "document updater",
                    "command": "/usr/bin/node /overleaf/services/document-updater/app.js",
                    "startup": "enabled",
                    "environment": document_updater_env,
                    "user": "www-data",
                },
                "filestore": {
                    "override": "replace",
                    "summary": "filestore",
                    "command": "/usr/bin/node /overleaf/services/filestore/app.js",
                    "startup": "enabled",
                    "environment": filestore_env,
                    "user": "www-data",
                },
                "history_v1": {
                    "override": "replace",
                    "summary": "history v1",
                    "command": "/usr/bin/node /overleaf/services/history-v1/app.js",
                    "startup": "enabled",
                    "environment": history_v1_env,
                    "user": "www-data",
                },
                "notifications": {
                    "override": "replace",
                    "summary": "notifications",
                    "command": "/usr/bin/node /overleaf/services/notifications/app.js",
                    "startup": "enabled",
                    "environment": notifications_env,
                    "user": "www-data",
                },
                "project_history": {
                    "override": "replace",
                    "summary": "project history",
                    "command": "/usr/bin/node /overleaf/services/project-history/app.js",
                    "startup": "enabled",
                    "environment": project_history_env,
                    "user": "www-data",
                },
                "real_time": {
                    "override": "replace",
                    "summary": "real time",
                    "command": "/usr/bin/node /overleaf/services/real-time/app.js",
                    "startup": "enabled",
                    "environment": real_time_env,
                    "user": "www-data",
                },
                "spelling": {
                    "override": "replace",
                    "summary": "spelling",
                    "command": "/usr/bin/node /overleaf/services/spelling/app.js",
                    "startup": "enabled",
                    "environment": spelling_env,
                    "user": "www-data",
                },
                "web_api": {
                    "override": "replace",
                    "summary": "web api",
                    "command": "/usr/bin/node /overleaf/services/web/app.js",
                    "startup": "enabled",
                    "environment": web_api_env,
                    "user": "www-data",
                },
                "web": {
                    "override": "replace",
                    "summary": "web",
                    "command": "/usr/bin/node /overleaf/services/web/app.js",
                    "startup": "enabled",
                    "environment": web_env,
                    "user": "www-data",
                },
            },
        }
        return ops.pebble.Layer(pebble_layer)


if __name__ == "__main__":  # pragma: nocover
    ops.main(OverleafK8sCharm)
