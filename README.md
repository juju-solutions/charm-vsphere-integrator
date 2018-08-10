# Overview

This charm acts as a proxy to VMWare vSphere and provides an [interface][] to
provide a set of credentials for a somewhat limited project user to the
applications that are related to this charm.

## Usage

When on a vSphere cloud, this charm can be deployed, granted trust via Juju to
access vSphere, and then related to an application that supports the
[interface][].

For example, [CDK][] has support for this, and can be deployed with the
following bundle overlay:

```yaml
applications:
  vsphere-integrator:
    charm: cs:~containers/vsphere-integrator
    num_units: 1
relations:
  - ['vsphere-integrator', 'kubernetes-master']
  - ['vsphere-integrator', 'kubernetes-worker']
```

Using Juju 2.4 or later:

```
juju deploy cs:canonical-kubernetes --overlay ./k8s-vsphere-overlay.yaml
juju trust vsphere-integrator
```

To deploy with earlier versions of Juju, you will need to provide the cloud
credentials via the `credentials`, charm config options.

# Resource Usage Note

By relating to this charm, other charms can directly allocate resources, such
as PersistentDisk volumes, which could lead to cloud charges and count against
quotas.  Because these resources are not managed by Juju, they will not be
automatically deleted when the models or applications are destroyed, nor will
they show up in Juju's status or GUI.  It is therefore up to the operator to
manually delete these resources when they are no longer needed, using the
vCenter console or API.

# Examples

Following are some examples using vSphere integration with CDK.

## Creating a pod with a PersistentDisk-backed volume

This script creates a busybox pod with a persistent volume claim backed by
vSphere's PersistentDisk.

```sh
#!/bin/bash

# create a storage class using the `kubernetes.io/cinder` provisioner
kubectl create -f - <<EOY
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: mystorage
provisioner: kubernetes.io/vsphere-volume
parameters:
  diskformat: zeroedthick
  fstype:     ext  4
EOY

# create a persistent volume claim using that storage class
kubectl create -f - <<EOY
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: testclaim
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 100Mi
  storageClassName: mystorage
EOY

# create the busybox pod with a volume using that PVC:
kubectl create -f - <<EOY
apiVersion: v1
kind: Pod
metadata:
  name: busybox
  namespace: default
spec:
  containers:
    - image: busybox
      command:
        - sleep
        - "3600"
      imagePullPolicy: IfNotPresent
      name: busybox
      volumeMounts:
        - mountPath: "/pv"
          name: testvolume
  restartPolicy: Always
  volumes:
    - name: testvolume
      persistentVolumeClaim:
        claimName: testclaim
EOY
```

[interface]: https://github.com/juju-solutions/interface-vsphere-integration
[CDK]: https://jujucharms.com/canonical-kubernetes
