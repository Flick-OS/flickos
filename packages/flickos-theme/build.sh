#!/bin/sh
# Build FlickOS-Arc-Dark and FlickOS-Arc (GTK 3 and GTK 4) from the Sass in src/
# into build/usr/share/themes/. Needs sassc and glib-compile-resources.
#
# Each theme folder has what arc-theme's has: gtk.css and gtk-dark.css, which
# import the compiled stylesheet from gtk.gresource (with the PNG assets it
# refers to). GTK 3 also gets src/frame-*.css after the import.
set -e

cd "$(dirname "$0")"
OUT="$PWD/build"
rm -rf "$OUT"

for variant in dark light; do
    case $variant in
        dark)  NAME=FlickOS-Arc-Dark; MAIN="dark" ;;
        light) NAME=FlickOS-Arc;      MAIN="dark light" ;;
    esac
    for gtk in 3.0 4.0; do
        DEST="$OUT/usr/share/themes/$NAME/gtk-$gtk"
        WORK="$OUT/work/$variant-$gtk"
        PREFIX="/org/flickos/theme/$variant/gtk-$gtk"
        mkdir -p "$DEST" "$WORK/assets"
        cp src/assets/*.png "$WORK/assets/"

        # arc-theme's stylesheets: the dark one for both themes, the light
        # one too for FlickOS-Arc (its gtk.css is light, its gtk-dark.css dark).
        for v in $MAIN; do
            if [ "$v" = dark ]; then css=gtk-main-dark.css; else css=gtk-main.css; fi
            sed -e "s|@variant@|$v|" -e "s|@transparency@|true|" \
                -e "s|@sass_path@|$PWD/src/gtk-$gtk/sass|" \
                "src/gtk-$gtk/sass/gtk.scss.in" > "$WORK/gtk-$v.scss"
            sassc --style compact "$WORK/gtk-$v.scss" "$WORK/$css"
        done

        {
            echo '<?xml version="1.0" encoding="UTF-8"?>'
            echo "<gresources><gresource prefix=\"$PREFIX\">"
            for f in "$WORK"/*.css "$WORK"/assets/*.png; do
                echo "<file>${f#"$WORK"/}</file>"
            done
            echo '</gresource></gresources>'
        } > "$WORK/theme.gresource.xml"
        glib-compile-resources --sourcedir="$WORK" --target="$DEST/gtk.gresource" "$WORK/theme.gresource.xml"

        # gtk.css follows the theme's own look, gtk-dark.css is the dark one.
        if [ "$variant" = dark ]; then light_css=gtk-main-dark.css; else light_css=gtk-main.css; fi
        for pair in "gtk.css:$light_css:$variant" "gtk-dark.css:gtk-main-dark.css:dark"; do
            file=${pair%%:*}; rest=${pair#*:}; css=${rest%%:*}; frame=${rest#*:}
            {
                echo "@import url(\"resource://$PREFIX/$css\");"
                if [ "$gtk" = 3.0 ]; then cat "src/frame-$frame.css"; fi
            } > "$DEST/$file"
        done
    done
done
rm -rf "$OUT/work"
