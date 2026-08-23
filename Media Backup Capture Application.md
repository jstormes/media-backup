# Media Backup Capture Application

A Ubuntu application to backup the contents of DVDs and BlueRays.

## The application

The application needs to be a native Linux application with support for bar code scanning and calling MakeMKV to copy the disks.

The application should have buttons with two ways to activate them.  The first by clicking the button with the mouse, the second by scanning a bar code on the button itself. In addition the the on screen bar codes/buttons, there will be bar codes on the DVD/Blu-Ray drives themselves.  Most of the general interactions can take place with the bar codes.

The flow of the application starts with the user scanning the bar code or pressing the "New Collection" button.  This should create a new collection object in memory with a unique identifier, that can also be used as a temporary directory name.  

This new collection will have an exposed state on the screen showing the objects current status the collection should have a section of the screen representing it's functions.  There can be multiple collections on the screen at any given time.  Each collection should be "contained" in a box with all of it's related functions and information inside the box.

## Scanning a UPC bar-code

After the collection is created, the use should be able to scan a bar-code on the disk case.  This will be the UPC for the movie, show, media collection.  Not all collections will have a UPS bar-code.  The screen will show a button/bar-code that the user can scan on the screen to then scan the UPC bar-code for capture.  Rescanning the button/bar-code will let the user replace the exiting UPC with a new one in case of error.

## Adding a disk

The DVD/BluRay drives will be labeled "Drive-A", "Drive-B" and so on.  Each drive will also have a unique bar-code the user can scan letting the application know what drive goes with current disk.  The user will scan the "Add Drive" button/bar-code then can the DVD/BluRay "Drive-<id>" to associate the drive to the content.

The first button/bar code inside the collection box should be the "Add Drive".  After the drive id is scanned, the application will ask the user for the disk number and season of the DVD/Blu-Ray put into the drive.  The default should be 1 and 1, with buttons for Not Applicable for both disk and season.  If the user is adding another disk the disk number should auto increment, but allow the user to override.  The season should default to 1, but if the user changes it, it should stay the same for all next added disk.  

The collection interface on the screen should show the disk and season after it is scanned and allow the user to change it at any time during the copy process.  

## Deleting a disk

If the user needs to start a disk over or put in the wrong disk in, the user should be able to remove the disk from the collection.  There should be a "Delete" button/bar-code next to each disk entry on screen allowing the user to delete it.  

## After the disk is copied

After the disk is copied it should appear at the top of the collection in the interface, along with it's disk number and season if applicable, or "na" if not applicable.  The delete button should still appear and let the user delete the disk from the collection.

## Completing the collection

At the bottom of the collection screen interface, there should be a "Collection Done" button/bar-code.  Scanning this button finishes the collection, letting the back end know all the data has been collected for the collection.  The copied MKVs files from the disks, and the collection data itself in a JSON file should all be in the directory under the unique name.  This is our backup copy of the disk.  Each disk should have it's own directory with it's own JSON containing the disk and season data.

## Deleting the collection 

If the collection cannot be completed, there should be a "Delete Collection" button/bar-code that moves all collected data into a "deleted" path for the system a remove from the storage drive later. 

## Multiple collections in process at once

The system will have several DVD/BluRay drives.  At any given time there can be multiple collections in process at once.  The above is just one collection.  The application should support multiple collections, with each showing on screen letting the user scroll down if needed to see the multiple collection in process.

## Finished collection

The system should show finished collections in another "tab", letting the user see completed collections that are still on disk.  The collections will eventually be moved to an archive system and removed from the local storage disk.  The system should only show collections still on the storage disk.

The system should show the full path the collection.