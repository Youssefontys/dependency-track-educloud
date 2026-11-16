# Provisioneert de VM uit README.md op Fontys Educloud (Apache CloudStack) en voert daarna
# zelf stap 1 t/m 4 van "Opzetten" uit: bestanden kopiëren, .env aanmaken, docker compose up,
# service/timer installeren. Daarna dt-bootstrap.py: stap 5 (wachtwoord) en de DT_API_KEY-regel
# van stap 7, via Dependency-Track's eigen REST API. Alleen het GitHub-token (stap 6) en het
# daadwerkelijk starten/inschakelen van de sbom-service (stap 8-9) blijven handwerk: dat token
# kan GitHub's eigen API bewust niet zelf aanmaken.
#
# Provisioners verbinden over SSH naar het privé-IP van de VM, dus `terraform apply` moet
# draaien vanaf een machine die al op de Fontys-VPN zit (dezelfde eis als de SSH-tunnel in
# README.md stap 4). Status: geschreven, nog niet tegen een echte Educloud-omgeving gedraaid.

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

  provisioner "file" {
    source      = "${path.module}/../dt-bootstrap.py"
    destination = "/tmp/dt-bootstrap.py"
  }

  provisioner "file" {
    source      = "${path.module}/../dt-meting.py"
    destination = "/tmp/dt-meting.py"
  }

  provisioner "remote-exec" {
    script = "${path.module}/bootstrap.sh"
  }

  # Los van bootstrap.sh: dt-bootstrap.py heeft zijn eigen, lange wachttijd nodig (de eerste
  # start van Dependency-Track duurt door het ophalen van de kwetsbaarhedendata zelf al een tijd).
  provisioner "remote-exec" {
    inline = ["sudo python3 /tmp/dt-bootstrap.py"]
  }
}
