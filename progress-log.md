# Progress log

## BITS OF INFO WE KEEP NEEDING:

workload container name: community
container resource: sharelatex/sharelatex:HEAD
so:

```
juju refresh overleaf-k8s --path ./overleaf-k8s_amd64.charm --resource sharelatex=sharelatex/sharelatex:HEAD --force-units
```

Take us to the charm container:

```
juju ssh --container community overleaf-k8s/0 bash
```

In there, these are useful Pebble commands:

```
/charm/bin/pebble plan
/charm/bin/pebble services
/charm/bin/pebble logs
```

To clean up removals: `juju resolved --no-retry unit/0`

To filter debug-log: `juju debug-log --include unit/0`

To format (to make VSCode happy): `tox -e format`

## The log

### Set up the working directory with upstream clones

 1768  mkdir overleaf-k8s
 1769  cd overleaf-k8s/
 1770  multipass mount ~/overleaf-k8s my-charm-vm:~/overleaf-k8s
 1771  git clone git@github.com:overleaf/toolkit.git
 1774  git clone git@github.com:overleaf/overleaf.git

### Set up Docker

    4  sudo addgroup --system docker
    5  sudo adduser $USER docker
    6  newgrp docker
    7  sudo snap install docker

### Get a different version of upstream and build the image

   45  cd overleaf/
   46  git checkout 972fbb7c67e82347909c6aba0165cf517ec82c29
   47  cd server-ce/
   49  make build-base
   50  make build-community
   51  docker images

### Initialize the charm

   75  cd overleaf-k8s-2
   76  charmcraft init --profile kubernetes

### Figure out how to provide the image to Juju

79  charmcraft pack
127  juju deploy ./overleaf-k8s_amd64.charm --resource community=sharelatex:registry

* 2024-08-15 Mounted drive appeared empty on the VM. Tried to remove it and remount, but removing it on the VM also removed it from the host. Recloned it on the host and remounted as overleaf-k8s-1, then tried to make the images again. Got an error related to Javascript. Searched on the overleaf GitHub repo for the tail of the path that the error seemed to be related to. Tony noticed the error line had been added just yesterday. [I forget exactly when] Remounted the drive as overleaf-k8s-2. Then in the overleaf clone inside of it, checked out a more recent branch by hash, then tried to build again, and that worked.

* 2024-08-22 juju deploy of the local charm failing with a cryptic Charm or bundle not found error.

* 2024-08-29 The Charm not found error could be coming from weirdness related to (1) Multipass or (2) strict confinement or (3) to us not using the correct resource syntax or needing to push the image to MicroK8s built-in registry.

(1) Tony tried it directly on his machine and he got the same error.
(2) In the deploy command, replaced juju with /snap/juju/current/bin/juju. That made no difference.
(3) We fixed the syntax. Also saved and tagged the image and then pushed it to MicroK8s. That made no difference.

  docker image save sharelatex/sharelatex -o sharelatex.img
  docker images
  docker tag 73a200831924 localhost:32000/sharelatex:registry
  docker push 10.238.98.84:32000/sharelatex
  docker push localhost:32000/sharelatex
  docker push localhost:32000/sharelatex:registry

Tony found out by accident that we'd mis-specified the resource in charmcraft.yaml. Once it fixed that, deploy finally ran...

Post-mortem: I should have been more careful about where I put that image and about what I typed into charmcraft.yaml and Juju should have given us a better error message.

Now, juju deploy runs but we get another error... Reran it multiple times with Ian as well and kept getting errors, always different. Ian noticed our .charm file was very large (>800MB) and that that was because it included our OCI image, so I deleted it and reran but still issues. Also bootstrapped a new controller and tried there but still issues. Tony said to run `charmcraft clean` and repack -- that final made the .charm file normal again (~8MB). However, `juju status` reveals further issues:

```
ubuntu@my-charm-vm:~/overleaf-k8s-2$ juju status
Model            Controller    Cloud/Region        Version  SLA          Timestamp
welcome-k8s-new  microk8s-new  microk8s/localhost  3.5.3    unsupported  10:54:54+02:00

App           Version  Status  Scale  Charm         Channel  Rev  Address        Exposed  Message
overleaf-k8s           error       1  overleaf-k8s             2  10.152.183.45  no       unknown container reason "ImagePullBackOff": Back-off pulling image "sharelatex:registry"

Unit             Workload  Agent  Address     Ports  Message
overleaf-k8s/0*  error     idle   10.1.98.97         unknown container reason "ImagePullBackOff": Back-off pulling image "sharelatex:registry"
```

PS Just out of curiosity, switched to the old controller and model and tried to deploy there too and I got the old error. So Ian was right that that controller was borked, for some reason. It's strange because it was a fresh controller.

Ian says the status looks like the image is not in the microk8s registry. Indeed, it is not:

ubuntu@my-charm-vm:~/overleaf-k8s-2$ microk8s.ctr image list
REF                                                                                                            TYPE                                                      DIGEST                                                                  SIZE      PLATFORMS                                                                                             LABELS
docker.io/calico/cni:v3.25.1                                                                                   application/vnd.docker.distribution.manifest.list.v2+json sha256:9a2c99f0314053aa11e971bd5d72e17951767bf5c6ff1fd9c38c4582d7cb8a0a 85.7 MiB  linux/amd64,linux/arm/v7,linux/arm64,linux/ppc64le,linux/s390x                                        io.cri-containerd.image=managed
docker.io/calico/cni@sha256:9a2c99f0314053aa11e971bd5d72e17951767bf5c6ff1fd9c38c4582d7cb8a0a                   application/vnd.docker.distribution.manifest.list.v2+json sha256:9a2c99f0314053aa11e971bd5d72e17951767bf5c6ff1fd9c38c4582d7cb8a0a 85.7 MiB  linux/amd64,linux/arm/v7,linux/arm64,linux/ppc64le,linux/s390x                                        io.cri-containerd.image=managed
docker.io/calico/kube-controllers:v3.25.1                                                                      application/vnd.docker.distribution.manifest.list.v2+json sha256:02c1232ee4b8c5a145c401ac1adb34a63ee7fc46b70b6ad0a4e068a774f25f8a 30.4 MiB  linux/amd64,linux/arm/v7,linux/arm64,linux/ppc64le,linux/s390x                                        io.cri-containerd.image=managed
docker.io/calico/kube-controllers@sha256:02c1232ee4b8c5a145c401ac1adb34a63ee7fc46b70b6ad0a4e068a774f25f8a      application/vnd.docker.distribution.manifest.list.v2+json sha256:02c1232ee4b8c5a145c401ac1adb34a63ee7fc46b70b6ad0a4e068a774f25f8a 30.4 MiB  linux/amd64,linux/arm/v7,linux/arm64,linux/ppc64le,linux/s390x                                        io.cri-containerd.image=managed
docker.io/calico/node:v3.25.1                                                                                  application/vnd.docker.distribution.manifest.list.v2+json sha256:0cd00e83d06b3af8cd712ad2c310be07b240235ad7ca1397e04eb14d20dcc20f 84.2 MiB  linux/amd64,linux/arm/v7,linux/arm64,linux/ppc64le,linux/s390x                                        io.cri-containerd.image=managed
docker.io/calico/node@sha256:0cd00e83d06b3af8cd712ad2c310be07b240235ad7ca1397e04eb14d20dcc20f                  application/vnd.docker.distribution.manifest.list.v2+json sha256:0cd00e83d06b3af8cd712ad2c310be07b240235ad7ca1397e04eb14d20dcc20f 84.2 MiB  linux/amd64,linux/arm/v7,linux/arm64,linux/ppc64le,linux/s390x                                        io.cri-containerd.image=managed
docker.io/cdkbot/hostpath-provisioner:1.5.0                                                                    application/vnd.docker.distribution.manifest.list.v2+json sha256:ac51e50e32b70e47077fe90928a7fe4d3fc8dd49192db4932c2643c49729c2eb 11.2 MiB  linux/amd64,linux/arm64,linux/ppc64le,linux/s390x                                                     io.cri-containerd.image=managed
docker.io/cdkbot/hostpath-provisioner@sha256:ac51e50e32b70e47077fe90928a7fe4d3fc8dd49192db4932c2643c49729c2eb  application/vnd.docker.distribution.manifest.list.v2+json sha256:ac51e50e32b70e47077fe90928a7fe4d3fc8dd49192db4932c2643c49729c2eb 11.2 MiB  linux/amd64,linux/arm64,linux/ppc64le,linux/s390x                                                     io.cri-containerd.image=managed
docker.io/coredns/coredns:1.10.1                                                                               application/vnd.docker.distribution.manifest.list.v2+json sha256:a0ead06651cf580044aeb0a0feba63591858fb2e43ade8c9dea45a6a89ae7e5e 15.4 MiB  linux/amd64,linux/arm/v7,linux/arm64,linux/mips64le,linux/ppc64le,linux/s390x                         io.cri-containerd.image=managed
docker.io/coredns/coredns@sha256:a0ead06651cf580044aeb0a0feba63591858fb2e43ade8c9dea45a6a89ae7e5e              application/vnd.docker.distribution.manifest.list.v2+json sha256:a0ead06651cf580044aeb0a0feba63591858fb2e43ade8c9dea45a6a89ae7e5e 15.4 MiB  linux/amd64,linux/arm/v7,linux/arm64,linux/mips64le,linux/ppc64le,linux/s390x                         io.cri-containerd.image=managed
docker.io/jujusolutions/charm-base:ubuntu-22.04                                                                application/vnd.oci.image.index.v1+json                   sha256:586ce71cc7953b0615994716a41528a7a8b70dfa3350efb644bb70d92f5affc6 71.2 MiB  linux/amd64,linux/arm64,linux/ppc64le,linux/s390x,unknown/unknown                                     io.cri-containerd.image=managed
docker.io/jujusolutions/charm-base:ubuntu-24.04                                                                application/vnd.oci.image.index.v1+json
```

So what went wrong with `docker push`?

  189  microk8s.ctr image list
  190  docker images
  191  juju status
  192  juju controllers
  193  juju switch microk8s-new
  194  juju status
  195  docker save sharelatex/sharelatex > mysharelateximage.tar
  196  microk8s ctr image import mysharelateximage.tar
  197  microk8s ctr images ls

### Study your application

#### Overleaf Notes

Notes from running the quick start instructions (ie. using Docker not Juju) and reading the various shell/docker files.

#### Getting kicked out

I believe this is from the "Phusion Image" that the image is built on - the Dockerfile (/overleaf/server-ce/Dockerfile) has this:

```
# Phusion Image timeouts before sending SIGKILL to processes
# ----------------------------------------------------------
ENV KILL_PROCESS_TIMEOUT 55
ENV KILL_ALL_PROCESSES_TIMEOUT 55
```

I think that's what kicks you out after 55 seconds. It's annoying but I guess there's some reason for it. I think if you rebuilt the Docker image with different numbers there it would change the behaviour.

#### init

Should change config to not have sibling containers (Pro only) `SIBLING_CONTAINERS_ENABLED = false`

Maybe should change config to not use Mongo to start with, to make it simpler? `MONGO_ENABLED = false`

Maybe should change config to not use Redis to start with, to make it simpler?  `REDIS_ENABLED = false` (although when I did this bin/start and bin/up still started redis...)

#### Starting (/bin/up)

Without Mongo or sibling containers, bin/up just does bin/docker-compose up

#### docker-compose

1. Checks image versions (skipping this should be fine, you're in control of the image)
2. Checks mongo version (likewise, you'll provide a specific Mongo via the relation)
3. Checks the config is valid (the hard-coded one you have will be fine, when you expose parts of that via `juju config` you can do validation then)
4. Checks that you're not using a version that has been pulled (retracted) (not important for now)
5. Checks environment variables are valid (same as #3)
6. Sets environment variables (this belongs in the Pebble layer for a charm, also see below)
7. Outputs debugging info (I guess you could add debugging logs with this info if you like, in __init__ probably)
8. Runs `docker compose` with whatever arg was provided

So the other key commands (start, stop) also just do the same thing but with a different `docker-compose` command

#### Services

The Docker config files are in toolkit/lib/ - I think *these* should actually also be Pebble services actually (we'll need the environment variables we did already as we do this, but not all of them for every service). Except for the mongo, redis, nginx ones, they should be done via relations, and sibling-containers and git-bridge (both Pro only).

If any of the required env variables are not in the ones we have then toolkit/lib/default.rc should have them. There are also some in config/variables.env

OVERLEAF_DATA_PATH <- probably should be a Juju storage mount, I think? But not necessary at first (except that every time the container is created I think you will loose the data? But maybe not with Mongo?)
MONGO_DATA_PATH <- I've never used the Mongo charm, does it actually provide storage and a path? Or do we need to somehow change this to be over an API?
REDIS_DATA_PATH <- Same here.

#### Other bin/ tools

##### bin/backup-config

Backs up the configuration file - probably not required if a charm is managing the config. But if it is for some reason then presumably an action.

##### bin/doctor

Checks if everything seems ok. Shouldn't be needed by someone using the charm. Could be useful if you make your own image/rock to check that e.g. all the dependencies are present.

##### bin/logs and bin/error-logs

Outputs (error) logs from various services. Ideally these would all be going to Loki.

##### bin/images

Just shows what images are avaialble, e.g.

```
ubuntu@overleaf:~/overleaf-k8s/toolkit$ sudo bin/images
---- Community Edition Images ----
REPOSITORY              TAG                                             IMAGE ID       CREATED       SIZE
sharelatex/sharelatex   main                                            918195136e1a   2 weeks ago   2.05GB
sharelatex/sharelatex   main-169723f492eb083ae3ebd5c6038b04a7a0bdf4a7   918195136e1a   2 weeks ago   2.05GB
sharelatex/sharelatex   5.1.1                                           28f666f253f8   5 weeks ago   2.07GB
---- Server Pro Images ----
REPOSITORY   TAG       IMAGE ID   CREATED   SIZE
---- TexLive Images ----
REPOSITORY   TAG       IMAGE ID   CREATED   SIZE
---- Git Bridge Images ----
REPOSITORY   TAG       IMAGE ID   CREATED   SIZE
```

Not needed.

##### bin/upgrade

Would be replaced by upgrade-charm event plus the upgrade that Juju does itself. Something for much later on!

##### bin/shell

Same as `juju ssh unit/0 bash`

##### bin/run-script

Roughly the same as `juju exec` or `juju ssh`

##### bin/rename-rc-vars, bin/rename-env-vars-5-0

Tools for upgrading, shouldn't be needed since you're starting with a more modern version.

##### bin/mongo

Replaced by the relation.

#### /sbin/my_init

This is something from [Phusion](https://github.com/phusion/baseimage-docker). We already have an init process (Pebble) that we like a lot so we should use that instead.

Basically, it will run all the scripts that are in overleaf/server-ce/init_scripts/

##### 000_check_for_old_bind_mounts_5.sh, 000_check_for_old_env_vars_5.sh

An upgrade thing, not needed.

##### 100_generate_secrets.sh

The charm should do this, creating Juju secrets and putting them in the appropriate environment variables.

##### 100_make_overleaf_data_dirs.sh

If these don't already exist in the container then the charm should do this.

##### 100_restore_site_status.sh

I guess this should be done in a `start` and `stop` handler or something like that? Not sure what the scaling story is here, or maybe the plan is that there is only one overleaf unit?

##### 100_set_docker_host_ipaddress.sh

I believe Juju should handle this for you.

##### 200_nginx_config_template.sh

Maybe needed when you get to the nginx relation, maybe the nginx charm will be doing this for you though.

##### 300_delete_old_logs.sh

I think it's saying this isn't needed any more. Would be ideal if the logs only went to Loki and didn't end up in the container anyway.

##### 500_check_db_access.sh

Just a check, can be skipped or be part of a collect-status check.

##### 900_run_web_migrations.sh

Presumably something for upgrade-charm event handler, figure it out later!

##### 910_check_texlive_images

I think this is also just a check, so skipped or part of collect-status. Hard to see how these would actually go wrong.

##### 910_initiate_doc_version_recovery

I think this is something that recovers when there's been a crash. Definitely something to figure out another day.

##### ../init_preshutdown_scripts/

Probably things that should be done in a `stop` handler - I didn't look at the individual files.

#### overleaf/runit/

I believe these are the main overleaf services that Phusion runs, so each of these should be (yet another!) Pebble service.

For example, this is `web-overleaf/run`

```sh
#!/bin/bash

NODE_PARAMS=""
if [ "$DEBUG_NODE" == "true" ]; then
    echo "running debug - web"
    NODE_PARAMS="--inspect=0.0.0.0:40000"
fi

source /etc/overleaf/env.sh
export LISTEN_ADDRESS=127.0.0.1
export ENABLED_SERVICES="web"
export WEB_PORT="4000"

exec /sbin/setuser www-data /usr/bin/node $NODE_PARAMS /overleaf/services/web/app.js >> /var/log/overleaf/web.log 2>&1
```

I think that would be a Pebble layer service dict like this (ignoring the debug option, and figuring out the logging later):

```python
{
    "command": "/usr/bin/node /overleaf/services/web/app.js >> /var/log/overleaf/web.log 2>&1",
    "summary": "Overleaf web service",
    "description": Node service blah blah",
    "environment": {
        "LISTEN_ADDRESS": "127.0.0.1",
        "ENABLED_SERVICES": "web",
        "WEB_PORT": "4000",
        # These are all from env.sh - I would guess that they maybe are not all needed here?
	"CHAT_HOST=127.0.0.1",
	"CLSI_HOST=127.0.0.1",
	"CONTACTS_HOST=127.0.0.1",
	"DOCSTORE_HOST=127.0.0.1",
	"DOCUMENT_UPDATER_HOST=127.0.0.1",
	"DOCUPDATER_HOST=127.0.0.1",
	"FILESTORE_HOST=127.0.0.1",
	"HISTORY_V1_HOST=127.0.0.1",
	"NOTIFICATIONS_HOST=127.0.0.1",
	"PROJECT_HISTORY_HOST=127.0.0.1",
	"REALTIME_HOST=127.0.0.1",
	"SPELLING_HOST=127.0.0.1",
	"WEB_HOST=127.0.0.1",
	"WEB_API_HOST=127.0.0.1",
    },
    "user": "www-data",
}
```

I think a good organisation might be a layer for everything that's in `runit` (the "overleaf" layer) and then separate layers for each of the things in toolkit/lib (additional third party services that Overleaf uses).

3 options with Pebble: (1) You have a container for each separate thing. But it gets tricky because you need to make them communicate. (2) One container with one layer. (3) One container with multiple layers. We should make this clear in the docs.


### Figure out why some things are not running

```
ubuntu@my-charm-vm:~/overleaf-k8s-4/charm$ juju status
Model          Controller    Cloud/Region        Version  SLA          Timestamp
welcome-k8s-5  microk8s-new  microk8s/localhost  3.5.3    unsupported  08:27:56+01:00

App           Version  Status  Scale  Charm         Channel   Rev  Address         Exposed  Message
mongodb-k8s            active      1  mongodb-k8s   6/stable   61  10.152.183.167  no
overleaf-k8s           error       1  overleaf-k8s             12  10.152.183.69   no       hook failed: "database-relation-changed"

Unit             Workload  Agent  Address      Ports  Message
mongodb-k8s/0*   active    idle   10.1.98.78          Primary
overleaf-k8s/0*  error     idle   10.1.98.119         hook failed: "database-relation-changed"
```

SSH into the community container to get the pebble logs: `/charm/bin/pebble logs > pebble-logs.txt`

Tried to copy the logs from the container to the VM. That only worked when we copied into home:
`juju scp --container community overleaf-k8s/0:/overleaf/pebble-logs.txt ~/my-pebble-logs.txt`

Try to do multipass transfer:
```
multipass transfer my-charm-vm:/tmp/my-pebble-logs.txt .
[2025-01-22T09:16:16.269] [error] [sftp] cannot open remote file /tmp/my-pebble-logs.txt: SFTP server: No such file
```

Figure out why Multipass mount is read only or give up trying to look at the logs this way. (Or why we still need to charmcraft pack locally.)

BTW We can't touch or mv files within the VM (only locally, to be synced to the mounted dir in the VM).

### Set up Redis

Found the library: https://charmhub.io/redis-k8s/libraries/redis

In charmcraft.yaml, declared charm-libs; defined the requires endpoint; then used charmcraft fetch-libs (had to run this locally, not in the VM).

In src/charm.py, imported the library; created the redis db object (docs missing); set up an observer for the custom event from the library (docs were missing or incomplete); paired it with the config handler, using the holistic approach; added a few lines to that handler to ensure that the redis integration is added before proceeding. We also added the REDIS_ENABLED and REDIS_HOST envvars (the latter: the value was from the redis library).

In the library docs, the on = RedisRelationCharmEvents() that overwrites the Ops on is in fact necessary, because the library was developed in a slightly unusual way.

Redis appeared in an error state. Tried to remove it and even resolve errors, but, strangely, we're told "ERROR unit "redis-k8s/0" is not in an error state", even though juju status still shows it in error.

```
ubuntu@my-charm-vm:~/overleaf-k8s-4/charm$ juju status
Model          Controller    Cloud/Region        Version  SLA          Timestamp
welcome-k8s-5  microk8s-new  microk8s/localhost  3.5.3    unsupported  08:51:41+01:00

App           Version               Status       Scale  Charm         Channel        Rev  Address         Exposed  Message
mongodb-k8s                         active           1  mongodb-k8s   6/stable        61  10.152.183.167  no
overleaf-k8s                        maintenance      1  overleaf-k8s                  14  10.152.183.69   no
redis-k8s     ubuntu/redis@691f315  waiting        0/1  redis-k8s     latest/stable    7  10.238.98.84    no

Unit             Workload     Agent   Address      Ports     Message
mongodb-k8s/0*   active       idle    10.1.98.86             Primary
overleaf-k8s/0*  maintenance  idle    10.1.98.110
redis-k8s/0*     error        failed  10.1.98.97   6379/TCP  unknown container reason "Unknown":
ubuntu@my-charm-vm:~/overleaf-k8s-4/charm$ juju resolved --no-retry redis-k8s/0
ERROR unit "redis-k8s/0" is not in an error state
ubuntu@my-charm-vm:~/overleaf-k8s-4/charm$
```

### Figure out connecting to MondoDB

We had what looked like a good connection string but it was not working. To
figure this out, Tony connected to the MongoDB charm container and looked at
the `metadata.yaml` file to get the name of the workload container and then
connected to the MongoDB container:

`juju ssh --container mongod mongok8s/0 bash`

And ran `mongosh overleaf`, which shows the full connection string being used.
Tony compared this one to the one in the Pebble plan and figured out (after
staring at the strings for far too long) that there was a typo in the port,
27107 instead of 27017 (pretty sure Tony's mistake a while back, he transposes
numbers sometimes these days, it's very annoying).

### Figure out why some things are not running

Done. All the services are up now!

### Figure out what port overleaf is served on

The [nginx configuration](https://github.com/overleaf/overleaf/blob/2c91363745011fa5128ed2003c366a8add1aa4cb/server-ce/nginx/overleaf.conf#L13) shows that it listens on:

* port 4000 for the main web interface
* port 3026 for `/socket.io` - I think this is the "realtime" service
* port 8080 for some "output files" - I think this is downloading static generated files

Also: by default it binds to 127.0.0.0 not 0.0.0.0 so it won't respond outside of the container (we need to set up ingress).

Tony ran `./bin/up` in the toolkit to see what it was doing in Docker and could curl localhost:4000 there.

Doing a `curl localhost:4000` in the workload container gives an HTTP response from Overleaf!

### Install ingress

What we did: installed traefik, added the lib instantiation in `__init__`, added the observers (not doing anything at the moment apart logging). `fetch-libs` in `charmcraft.yaml`, fetched them. 

TODO: these docs: https://charmhub.io/traefik-k8s/libraries/ingress are more up to date than these docs: https://charmhub.io/traefik-k8s/docs/integrating -- and why do both exist, when they are telling the same story?

Installing the Traefik charm by itself gave a bunch of errors. Installed a whole bundle of (observability?) charms and then it was working.

TODO: trim this down to only the ones that are needed.

We get a 504 Bad Gateway when trying to `curl` overleaf outside of the workload container.

Added `set_ports` in the charm - the Traefik troubleshooting guide says that the port must be open.

The troubleshooting guide also says that we need to be listening on all ports. Unclear the difference between `0.0.0.0:4000` and `*:4000`. Setting `OVERLEAF_LISTEN_IP` doesn't seem to make any change.

The answer is that it's the `LISTEN_IP` in the Pebble plan that needs to be `0.0.0.0` - the web *API* was set to that, but the API is probably fine just listening in the container. It's the *web* service that needs
to be externally accessible for traefik.

To test this, we need to:

#### Set up a fake demo.local DNS name

`demo.local` is the default for our traefik install.

```
ubuntu@overleaf:~/overleaf-k8s-operator/charm$ juju config traefik external_hostname
demo.local
```

In the *host*, `sudo nano /etc/hosts` (or whatever editor) and add a line

```
# For overleaf
10.1.216.210 demo.local
```

Where the IP address is the one from Juju status for traefik, like:

```
Unit             Workload  Agent  Address       Ports     Message
[...]
]traefik/0*       active    idle   10.1.216.210            Serving at demo.local
```

#### Route traffic between the host and the multipass VM

(The COS chapter in the K8s tutorial has instructions for this).

Run `multipass info overleaf`, to get something like:

```
$ multipass info overleaf
Name:           overleaf
State:          Running
Snapshots:      0
IPv4:           10.21.40.69
                172.18.0.1
                172.17.0.1
                10.231.81.1
                10.1.216.192
Release:        Ubuntu 24.04 LTS
Image hash:     0e25ca6ee9f0 (Ubuntu 24.04 LTS)
CPU(s):         4
Load:           1.11 1.81 2.29
Disk usage:     54.2GiB out of 77.4GiB
Memory usage:   3.8GiB out of 7.7GiB
Mounts:         /home/tameyer/code/overleaf-k8s-operator => /home/ubuntu/overleaf-k8s-operator
                    UID map: 1000:default
                    GID map: 1000:default
```

And then use the IP from `IPv4` there and the traefik IP from Juju status and do:

```
sudo ip route add 10.1.216.0/24 via 10.21.40.69 
```

The exact IP/32 would probably have also been fine. That .0/24 will be routing everything in the subnet into the VM, not just traefik.

**This only lasts until you reboot**.

Then open a browser *on the host* and go to `https://demo.local/m-overleaf-k8s/login` and go past the certificate warning.

Some things are busted:

* Looks like no static files (CSS, images, etc). Need to figure out what is meant to serve these - probably it was nginx, so maybe we need a charm for that or a service in our charm? Not sure what the charming story is here.
* I couldn't log in because the dummy user is "overleaf" but it wants it to be an email, so will try "overleaf@example.com" next time.
* I think the certificate stuff can be figured out, although it would be simpler with a real domain name (I think we could use the Let's Encrypt charm then and it would all just work).
* The URL has `m-overleaf-k8s` (the `m` is the model name, the rest is the app name). I assume we can configure traefik to send things at the root of the domain to a specific model/app?

TODO: By the way, redis-k8s still dies on my every time I shut down multipass. Every time I start it up again I have to force remove it and then add it and integrate it again. This doesn't seem great, should maybe talk to the data people?

## Jobs to do

### Set unit/application status

We should observe unit/app collect status and set the status appropriately (for example, blocked when Mongo and Redis aren't available yet).

### Upgrade

TeX Live can be upgraded, and probably should either be as part of building the image or could be in the charm upgrade event.

See https://github.com/overleaf/toolkit/blob/d7e63cef6d36f47b51889280cc5698249db0ede2/doc/ce-upgrading-texlive.md

### Set the charm version

Pull this from git now that we're using it. Should be able to do a post-commit hook I think?

### Set the unit workload version

Presumably can pull from overleaf somehow.

### Storage

OVERLEAF_DATA_PATH is for a data volume of some type, probably this needs to be persistent and should be handled with Juju Storage.

### Observability

Normal COS integration.

### Doctor?

The toolkit has a nice "doctor" tool that helps with debugging. Maybe the charm could offer a doctor action?

https://github.com/overleaf/toolkit/blob/d7e63cef6d36f47b51889280cc5698249db0ede2/doc/the-doctor.md


