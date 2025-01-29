#!/usr/bin/env python3
# Copyright 2024 Ubuntu
# See LICENSE file for licensing details.

"""Charm the application."""

import logging

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.redis_k8s.v0.redis import RedisRelationCharmEvents, RedisRequires

logger = logging.getLogger(__name__)


class OverleafK8sCharm(ops.CharmBase):
    """Charm the application."""

    on = RedisRelationCharmEvents()

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on["community"].pebble_ready, self._configure_change)

        # Charm events defined in the database requires charm library.
        self.database = DatabaseRequires(self, relation_name="database", database_name="overleaf")
        self.framework.observe(self.database.on.database_created, self._configure_change)
        self.redis = RedisRequires(self, "redis")
        self.framework.observe(self.on.redis_relation_updated, self._configure_change)

    def _configure_change(self, event: ops.HookEvent):
        """Handle pebble-ready event."""
        if not self.model.get_relation("database"):
            logger.info("No relation to the MongoDB database yet.")
            return  # here's where the holistic approach makes thing easy -- you don't need to defer
        if not self.model.get_relation("redis"):
            logger.info("No relation to the Redis database yet.")
            return  # here's where the holistic approach makes thing easy -- you don't need to defer
        container = self.unit.containers["community"]
        if not container.can_connect():
            logger.info("Pebble not ready yet.")
            return
        # Add initial Pebble config layer using the Pebble API
        container.add_layer("Overleaf service", self._pebble_layer, combine=True)
        # Create nginx config:
        config = """
## ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ##
## ! This file was generated from a template ! ##
## ! See /etc/nginx/templates/               ! ##
## ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ! ##
daemon off;
user www-data;
worker_processes 3; # we replaced ${NGINX_WORKER_PROCESSES} with 3
pid /run/nginx.pid;

events {
	worker_connections 10; # we replaced ${NGINX_WORKER_CONNECTIONS} with 10
	# multi_accept on;
}

http {

	##
	# Basic Settings
	##

	sendfile on;
	tcp_nopush on;
	tcp_nodelay on;
	keepalive_timeout 120; # we replaced ${NGINX_KEEPALIVE_TIMEOUT} with 120
	types_hash_max_size 2048;
	# server_tokens off;

	# server_names_hash_bucket_size 64;
	# server_name_in_redirect off;

	include /etc/nginx/mime.types;
	default_type application/octet-stream;

	##
	# Logging Settings
	##

	access_log /var/log/nginx/access.log;
	error_log /var/log/nginx/error.log;

	##
	# Gzip Settings
	##

	gzip on;
	gzip_disable "msie6";
	gzip_proxied any; # allow upstream server to compress.

	client_max_body_size 50m;

	# gzip_vary on;
	# gzip_proxied any;
	# gzip_comp_level 6;
	# gzip_buffers 16 8k;
	# gzip_http_version 1.1;
	# gzip_types text/plain text/css application/json application/x-javascript text/xml application/xml application/xml+rss text/javascript;

	##
	# nginx-naxsi config
	##
	# Uncomment it if you installed nginx-naxsi
	##

	#include /etc/nginx/naxsi_core.rules;

	##
	# nginx-passenger config
	##
	# Uncomment it if you installed nginx-passenger
	##

	#passenger_root /usr;
	#passenger_ruby /usr/bin/ruby;

	##
	# Virtual Host Configs
	##

	include /etc/nginx/conf.d/*.conf;
	include /etc/nginx/sites-enabled/*;
}

        """
        container.push("/etc/nginx/nginx.conf", config)

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
            return default

        relation_id = self.database.relations[0].id
        relation_data = self.database.fetch_relation_data()[relation_id]

        endpoints = relation_data.get("endpoints", "").split(",")
        if len(endpoints) < 1:
            return default

        primary_endpoint = endpoints[0].split(":")
        if len(primary_endpoint) < 2:
            return default

        data = {
            "MONGO_USER": relation_data.get("username"),
            "MONGO_PASSWORD": relation_data.get("password"),
            "MONGO_HOST": primary_endpoint[0],
            "MONGO_PORT": primary_endpoint[1],
            "MONGO_DB": relation_data.get("database"),
        }

        if None in (
            data["MONGO_USER"],
            data["MONGO_PASSWORD"],
            data["MONGO_DB"],
        ):
            return default

        return data

    @property
    def _pebble_layer(self):
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
        database_settings = self.get_relation_data()
        common_env = {
            "CHAT_HOST": "127.0.0.1",
            "CLSI_HOST": "127.0.0.1",
            "CONTACTS_HOST": "127.0.0.1",
            "DOCSTORE_HOST": "127.0.0.1",
            "DOCUMENT_UPDATER_HOST": "127.0.0.1",
            "DOCUPDATER_HOST": "127.0.0.1",
            "FILESTORE_HOST": "127.0.0.1",
            "HISTORY_V1_HOST": "127.0.0.1",
            # For Overleaf, MONGO_ENABLED=true doesn't mean "use MongoDB", it
            # means that the Overleaf image should use the included MongoDB.
            # For the charm, we want to use MongoDB provided by an integration
            # instead.
            "MONGO_ENABLED": "false",
            "MONGO_URL": f"mongodb://{database_settings['MONGO_USER']}:{database_settings['MONGO_PASSWORD']}@{database_settings['MONGO_HOST']}:{database_settings['MONGO_PORT']}/{database_settings['MONGO_DB']}",
            "NOTIFICATIONS_HOST": "127.0.0.1",
            "PROJECT_HISTORY_HOST": "127.0.0.1",
            "REALTIME_HOST": "127.0.0.1",
            # Similar to MONGO_ENABLED, this means "a Redis will be provided",
            # not "don't use Redis".
            "REDIS_ENABLED": "false",
            "REDIS_HOST": self.redis.relation_data.get("hostname"),
            "SPELLING_HOST": "127.0.0.1",
            "WEB_HOST": "127.0.0.1",
            "WEB_API_HOST": "127.0.0.1",
        }
        #         command = "/sbin/my_init"
        # #TODO figure out the right command (pebble plan seems to be working but the workload service isn't running)
        #         env = {
        #              "OVERLEAF_IMAGE_NAME":"sharelatex/sharelatex",
        # "OVERLEAF_DATA_PATH":"data/overleaf",
        # "SERVER_PRO":"false",
        # "OVERLEAF_LISTEN_IP":"127.0.0.1",
        # "OVERLEAF_PORT":"80",
        # "SIBLING_CONTAINERS_ENABLED":"true",
        # "DOCKER_SOCKET_PATH":"/var/run/docker.sock",
        # "MONGO_ENABLED":"true", #actually means overleaf should have its own mongodb
        # "MONGO_DATA_PATH":"data/mongo",
        # "MONGO_IMAGE":"mongo",
        # "MONGO_VERSION":"6.0",
        # "REDIS_ENABLED":"true",
        # "REDIS_DATA_PATH":"data/redis",
        # "REDIS_IMAGE":"redis:6.2",
        # "REDIS_AOF_PERSISTENCE":"true",
        # "GIT_BRIDGE_ENABLED":"false",
        # "GIT_BRIDGE_DATA_PATH":"data/git-bridge",
        # "NGINX_ENABLED":"false",
        # "NGINX_CONFIG_PATH":"config/nginx/nginx.conf",
        # "NGINX_HTTP_PORT":"80",
        # "NGINX_HTTP_LISTEN_IP":"127.0.1.1",
        # "NGINX_TLS_LISTEN_IP":"127.0.1.1",
        # "TLS_PRIVATE_KEY_PATH":"config/nginx/certs/overleaf_key.pem",
        # "TLS_CERTIFICATE_PATH":"config/nginx/certs/overleaf_certificate.pem",
        # "TLS_PORT":"443",
        # "OVERLEAF_APP_NAME":"Our Overleaf Instance",
        # "ENABLED_LINKED_FILE_TYPES":"project_file,project_output_file",
        # "ENABLE_CONVERSIONS":"true",
        # "EMAIL_CONFIRMATION_DISABLED":"true",
        #         }
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
        notifications_env = common_env.copy()
        notifications_env.update({"LISTEN_ADDRESS": "127.0.0.1"})
        project_history_env = common_env.copy()
        project_history_env.update({"LISTEN_ADDRESS": "127.0.0.1"})
        real_time_env = common_env.copy()
        real_time_env.update({"LISTEN_ADDRESS": "127.0.0.1"})
        web_api_env = common_env.copy()
        web_api_env.update(
            {"LISTEN_ADDRESS": "0.0.0.0", "ENABLED_SERVICES": "api", "METRICS_APP_NAME": "web-api"}
        )
        web_env = common_env.copy()
        web_env.update(
            {"LISTEN_ADDRESS": "127.0.0.1", "ENABLED_SERVICES": "web", "WEB_PORT": "4000"}
        )
        pebble_layer = {
            # TODO: 3 services not running: history_v1, nginx, real-time
            "summary": "Overleaf service",
            "description": "pebble config layer for Overleaf server",
            "services": {
                "chat": {
                    "override": "replace",
                    "summary": "chat",
                    "command": "/usr/bin/node /overleaf/services/chat/app.js >> /var/log/overleaf/chat.log 2>&1",
                    "startup": "enabled",
                    "environment": chat_env,
                    "user": "www-data",
                },
                "clsi": {
                    "override": "replace",
                    "summary": "clsi",
                    "command": "/usr/bin/node /overleaf/services/clsi/app.js >> /var/log/overleaf/clsi.log 2>&1",
                    "startup": "enabled",
                    "environment": clsi_env,
                    "user": "www-data",
                },
                "contacts": {
                    "override": "replace",
                    "summary": "contacts",
                    "command": "/usr/bin/node /overleaf/services/contacts/app.js >> /var/log/overleaf/contacts.log 2>&1",
                    "startup": "enabled",
                    "environment": contacts_env,
                    "user": "www-data",
                },
                "docstore": {
                    "override": "replace",
                    "summary": "docstore",
                    "command": "/usr/bin/node /overleaf/services/docstore/app.js >> /var/log/overleaf/docstore.log 2>&1",
                    "startup": "enabled",
                    "environment": docstore_env,
                    "user": "www-data",
                },
                "document_updater": {
                    "override": "replace",
                    "summary": "document updater",
                    "command": "/usr/bin/node /overleaf/services/document-updater/app.js >> /var/log/overleaf/document-updater.log 2>&1",
                    "startup": "enabled",
                    "environment": document_updater_env,
                    "user": "www-data",
                },
                "filestore": {
                    "override": "replace",
                    "summary": "filestore",
                    "command": "/usr/bin/node /overleaf/services/filestore/app.js >> /var/log/overleaf/filestore.log 2>&1",
                    "startup": "enabled",
                    "environment": filestore_env,
                    "user": "www-data",
                },
                "history_v1": {
                    "override": "replace",
                    "summary": "history v1",
                    "command": "/usr/bin/node /overleaf/services/history-v1/app.js >> /var/log/overleaf/history-v1.log 2>&1",
                    "startup": "enabled",
                    "environment": {"NODE_CONFIG_DIR": "/overleaf/services/history-v1/config"},
                    "user": "www-data",
                },
                "nginx": {
                    "override": "replace",
                    "summary": "nginx",
                    "command": "/usr/sbin/nginx",
                    "startup": "enabled",
                    "environment": {},
                    "user": "www-data",
                },
                "notifications": {
                    "override": "replace",
                    "summary": "notifications",
                    "command": "/usr/bin/node /overleaf/services/notifications/app.js >> /var/log/overleaf/notifications.log 2>&1",
                    "startup": "enabled",
                    "environment": notifications_env,
                    "user": "www-data",
                },
                "project_history": {
                    "override": "replace",
                    "summary": "project history",
                    "command": "/usr/bin/node /overleaf/services/project-history/app.js >> /var/log/overleaf/project-history.log 2>&1",
                    "startup": "enabled",
                    "environment": project_history_env,
                    "user": "www-data",
                },
                "real_time": {
                    "override": "replace",
                    "summary": "real time",
                    "command": "/usr/bin/node /overleaf/services/real-time/app.js >> /var/log/overleaf/real-time.log 2>&1",
                    "startup": "enabled",
                    "environment": real_time_env,
                    "user": "www-data",
                },
                "spelling": {
                    "override": "replace",
                    "summary": "spelling",
                    "command": "/usr/bin/node /overleaf/services/spelling/app.js >> /var/log/overleaf/spelling.log 2>&1",
                    "startup": "enabled",
                    "environment": spelling_env,
                    "user": "www-data",
                },
                "web_api": {
                    "override": "replace",
                    "summary": "web api",
                    "command": "/usr/bin/node /overleaf/services/web/app.js >> /var/log/overleaf/web-api.log 2>&1",
                    "startup": "enabled",
                    "environment": web_api_env,
                    "user": "www-data",
                },
                "web": {
                    "override": "replace",
                    "summary": "web",
                    "command": "/usr/bin/node /overleaf/services/web/app.js >> /var/log/overleaf/web.log 2>&1",
                    "startup": "enabled",
                    "environment": web_env,
                    "user": "www-data",
                },
            },
        }
        return ops.pebble.Layer(pebble_layer)


if __name__ == "__main__":  # pragma: nocover
    ops.main(OverleafK8sCharm)
