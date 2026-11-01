[app]
title = URMC KAJJANSI
package.name = urmckajjansi
package.domain = com.urmc
source.dir = .
source.include_exts = py,png,jpg,json
version = 1.0
requirements = python3==3.11.5,hostpython3==3.11.5,kivy==2.3.0,pyjnius,android
orientation = portrait, landscape, landscape-reverse
fullscreen = 0
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png
android.presplash_color = #FFFFFF
android.api = 34
android.ndk = 25b
android.ndk_api = 24
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
