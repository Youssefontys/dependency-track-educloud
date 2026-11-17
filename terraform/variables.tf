variable "cloudstack_api_url" {
  description = "Educloud API-endpoint, eindigt op /client/api. Leeg laten kan ook: dan via CLOUDSTACK_API_URL."
  type        = string
  default     = null
}

variable "cloudstack_api_key" {
  description = "API key uit je Educloud-account (Account > genereer API key). Leeg laten kan ook: dan via CLOUDSTACK_API_KEY."
  type        = string
  sensitive   = true
  default     = null
}

variable "cloudstack_secret_key" {
  description = "Secret key uit je Educloud-account. Leeg laten kan ook: dan via CLOUDSTACK_SECRET_KEY."
  type        = string
  sensitive   = true
  default     = null
}

variable "instance_name" {
  description = "Naam van de VM in Educloud."
  type        = string
  default     = "dependency-track"
}

variable "service_offering" {
  description = "Exacte naam van het compute-profiel in Educloud (Compute Offerings in de UI). Minstens 4 GB RAM, zie README.md."
  type        = string
}

variable "template" {
  description = "Exacte naam van het OS-template in Educloud (Templates in de UI). Moet systemd, apt en Python 3 hebben; dit project gaat uit van Ubuntu."
  type        = string
}

variable "zone" {
  description = "Exacte naam van de Educloud-zone (Infrastructure > Zones in de UI)."
  type        = string
}

variable "network_id" {
  description = "ID of naam van het Educloud-netwerk voor de VM. Laat op null staan als je account maar één netwerk heeft."
  type        = string
  default     = null
}

variable "ssh_user" {
  description = "Login-gebruiker van het gekozen template. Controleer dit per template in Educloud (vaak 'ubuntu', soms 'student' of iets anders)."
  type        = string
  default     = "ubuntu"
}

variable "ssh_public_key_path" {
  description = "Lokaal pad naar je publieke SSH-sleutel, geïnjecteerd door CloudStack."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "ssh_private_key_path" {
  description = "Lokaal pad naar de bijbehorende private key, voor de provisioners die Terraform na het aanmaken uitvoert."
  type        = string
  default     = "~/.ssh/id_ed25519"
}
