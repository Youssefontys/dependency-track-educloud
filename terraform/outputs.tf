output "instance_id" {
  value = cloudstack_instance.dependency_track.id
}

output "vm_ip" {
  description = "Privé-IP van de VM binnen Educloud. Gebruik dit voor de SSH-tunnel uit LEESMIJ.md stap 4."
  # try(): tijdens plan kent Terraform de data source nog niet (die bestaat pas na apply),
  # anders faalt het indexeren van nic[0] al bij het plannen zelf.
  value = try(data.cloudstack_instance.dependency_track.nic[0].ip_address, null)
}
