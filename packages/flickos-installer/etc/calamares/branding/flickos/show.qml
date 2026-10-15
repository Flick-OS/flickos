// Slideshow shown while FlickOS installs. Reference:
// https://github.com/calamares/calamares/tree/calamares/src/branding/default
import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation
{
    id: presentation

    Timer {
        interval: 15000
        repeat: true
        running: presentation.activatedInCalamares
        onTriggered: presentation.goToNextSlide()
    }

    Slide {
        Image {
            id: logo1
            source: "logo.png"
            width: 160; height: 160
            fillMode: Image.PreserveAspectFit
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -40
        }
        Text {
            anchors.horizontalCenter: logo1.horizontalCenter
            anchors.top: logo1.bottom
            anchors.topMargin: 24
            width: 600
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.Center
            // The only place the weekly count (flickos-countme, PRIVACY.md) is announced.
            text: qsTr("Welcome to FlickOS.<br/>"
                     + "The installation is automatic from here and takes a few minutes.<br/><br/>"
                     + "<small>Once a week, FlickOS anonymously counts this computer: it sends only "
                     + "its version and roughly when it was installed. "
                     + "Turn this off in Settings → Privacy.</small>")
        }
    }

    Slide {
        Text {
            anchors.centerIn: parent
            width: 600
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.Center
            text: qsTr("<b>Getting around</b><br/><br/>"
                     + "Super+Enter: terminal &nbsp;·&nbsp; Super+D: applications<br/>"
                     + "Super+E: files &nbsp;·&nbsp; Super+B: web browser<br/>"
                     + "Right-click the desktop for the menu.")
        }
    }

    function onActivate() { }
    function onLeave() { }
}
