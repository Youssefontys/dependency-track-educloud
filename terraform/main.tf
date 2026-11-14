# Provisioneert de VM uit LEESMIJ.md op Fontys Educloud (Apache CloudStack) en voert daarna
# zelf stap 1 t/m 4 van "Opzetten" uit: bestanden kopiëren, .env aanmaken, docker compose up,
# service/timer installeren. Stap 5 t/m 9 (DT-wachtwoord, team/API-key, GitHub-token, timer
# inschakelen) blijven handwerk: dat kan niet voor het eerste bezoek aan de web-UI bestaan.
#
# Provisioners verbinden over SSH naar het privé-IP van de VM, dus `terraform apply` moet
# draaien vanaf een machine die al op de Fontys-VPN zit (dezelfde eis als de SSH-tunnel in
# LEESMIJ.md stap 4). Status: geschreven, nog niet tegen een echte Educloud-omgeving gedraaid.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    cloudstack = {
      source  = "cloudstack/cloudstack"
      # 0.5.0 is de nieuwste release volgens de eigen README van het project op 2026-10-20;
      # check de Terraform Registry voor een nieuwere versie voor je dit gebruikt.
      version = "~> 0.5.0"
    }
  }
}

provider "cloudstack" {
  # Leeg laten werkt ook: dan pakt de provider CLOUDSTACK_API_URL / CLOUDSTACK_API_KEY /
  # CLOUDSTACK_SECRET_KEY uit de omgeving, wat de sleutels uit terraform.tfvars en dus uit
  # een eventuele toekomstige git-historie houdt.
  api_url    = var.cloudstack_api_url
  api_key    = var.cloudstack_api_key
  secret_key = var.cloudstack_secret_key
}

resource "cloudstack_ssh_keypair" "dt_admin" {
  name       = "${var.instance_name}-admin"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "cloudstack_instance" "dependency_track" {
  name             = var.instance_name
  service_offering = var.service_offering
  template         = var.template
  zone             = var.zone
  network_id       = var.network_id
  keypair          = cloudstack_ssh_keypair.dt_admin.name
}

# De cloudstack_instance-resource exporteert zelf geen IP (alleen id en display_name volgens
# de provider-docs), dus het IP van de net aangemaakte VM met deze data source opzoeken.
data "cloudstack_instance" "dependency_track" {
  filter {
    name  = "name"
    value = cloudstack_instance.dependency_track.name
  }

  depends_on = [cloudstack_instance.dependency_track]
}

resource "null_resource" "bootstrap" {
  depends_on = [data.cloudstack_instance.dependency_track]

  triggers = {
    instance_id = cloudstack_instance.dependency_track.id
  }

  connection {
    type        = "ssh"
    host        = data.cloudstack_instance.dependency_track.nic[0].ip_address
    user        = var.ssh_user
    private_key = file(pathexpand(var.ssh_private_key_path))
    timeout     = "3m"
  }

  provisioner "file" {
    source      = "${path.module}/../compose.yaml"
    destination = "/tmp/compose.yaml"
  }

  provisioner "file" {
    source      = "${path.module}/../sbom-naar-dtrack.py"
    destination = "/tmp/sbom-naar-dtrack.py"
  }

  provisioner "file" {
    source      = "${path.module}/../sbom-naar-dtrack.service"
    destination = "/tmp/sbom-naar-dtrack.service"
  }

  provisioner "file" {
    source      = "${path.module}/../sbom-naar-dtrack.timer"
    destination = "/tmp/sbom-naar-dtrack.timer"
  }

  provisioner "file" {
    source      = "${path.module}/../sbom-naar-dtrack.env.example"
    destination = "/tmp/sbom-naar-dtrack.env.example"
  }

  provisioner "remote-exec" {
    script = "${path.module}/bootstrap.sh"
  }
}
