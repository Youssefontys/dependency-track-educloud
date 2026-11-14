output "instance_id" {
  value = cloudstack_instance.dependency_track.id
}

output "vm_ip" {
  description = "Privé-IP van de VM binnen Educloud. Gebruik dit voor de SSH-tunnel uit LEESMIJ.md stap 4."
  value       = data.cloudstack_instance.dependency_track.nic[0].ip_address
}
